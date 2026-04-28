import asyncio
import hashlib
import logging
from datetime import date, timedelta
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.dashboard.adapter.outbound.external.dart_announcement_client import (
    DartAnnouncementClient,
)
from app.domains.dashboard.adapter.outbound.external.dart_corporate_event_client import (
    DartCorporateEventClient,
)
from app.domains.dashboard.application.port.out.asset_type_port import AssetTypePort
from app.domains.dashboard.application.port.out.etf_holdings_port import EtfHoldingsPort
from app.domains.dashboard.application.port.out.sec_edgar_announcement_port import (
    SecEdgarAnnouncementPort,
)
from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.application.port.out.yfinance_corporate_event_port import (
    YahooFinanceCorporateEventPort,
)
from app.domains.dashboard.application.response.announcement_response import AnnouncementsResponse
from app.domains.dashboard.application.response.corporate_event_response import CorporateEventsResponse
from app.domains.dashboard.application.usecase.get_announcements_usecase import (
    GetAnnouncementsUseCase,
)
from app.domains.dashboard.application.usecase.get_corporate_events_usecase import (
    GetCorporateEventsUseCase,
)
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
)
from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.application.port.out.macro_news_search_port import (
    MacroNewsSearchPort,
)
from app.domains.history_agent.application.port.out.related_assets_port import (
    GprIndexPort,
    MacroContextEvent,
    RelatedAssetsPort,
)
from app.domains.history_agent.application.response.timeline_response import (
    HypothesisResult,
    TimelineEvent,
    TimelineResponse,
)
from app.domains.history_agent.application.service.event_classifier_service import (
    EventClassifierService,
)
from app.domains.history_agent.application.service.event_importance_service import (
    EventImportanceService,
)
from app.domains.history_agent.application.service.macro_reason_service import (
    enrich_type_b_reasons,
)
from app.domains.history_agent.application.service.text_utils import (
    needs_korean_summary,
)
from app.domains.history_agent.application.service.title_generation_service import (
    FALLBACK_TITLE,
    TITLE_MODEL,
    announcement_title,
    enrich_macro_titles,
    enrich_other_titles,
    is_pseudo_announcement_title_str,
)
from app.domains.history_agent.domain.entity.event_enrichment import (
    EventEnrichment,
    compute_detail_hash,
)
from app.domains.stock.market_data.application.port.out.event_impact_metric_repository_port import (
    EventImpactMetricRepositoryPort,
)
from app.domains.stock.market_data.domain.entity.event_impact_metric import (
    EventImpactMetric,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

_CACHE_TTL = 3600
# v8: KR1/KR2/KR3 — TimelineEvent 에 macro_type/reason/reason_confidence/reason_evidence 추가.
# 옵셔널 필드라 v7 직렬화 역호환은 되지만, stale cache 는 신규 필드 미반영이라 의미 없음.
_CACHE_VERSION = "v8"

_SUPPORTED_ASSET_TYPES = {"EQUITY", "INDEX", "ETF"}

# ── 인과관계 자동 호출 기준 ─────────────────────────────────────
# TRIGGER_TYPES는 계약이므로 코드에 유지. PRE/POST_DAYS는 settings로 이동.
_CAUSALITY_TRIGGER_TYPES = {"SURGE", "PLUNGE"}
_MAX_CAUSALITY_EVENTS = 3


def _causality_window_days() -> tuple[int, int]:
    s = get_settings()
    return s.history_causality_pre_days, s.history_causality_post_days

# ── 공시 중복 제거 ─────────────────────────────────────────────
# 이중상장(예: ADR) 기업에서 DART/SEC EDGAR가 같은 날 유사 공시를 발행할 때 병합.
# 소스 우선순위: 낮은 숫자일수록 우선. DART > SEC > YAHOO > 기타.
_ANNOUNCEMENT_SOURCE_PRIORITY = {"DART": 0, "SEC": 1, "SEC_EDGAR": 1, "YAHOO": 2}
_ANNOUNCEMENT_DEDUP_THRESHOLD = 0.8


def _jaccard_similarity(a: str, b: str) -> float:
    """공백 분할 기반 자카드 유사도. 짧은 공시 헤드라인에 충분하다."""
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _announcement_source_rank(source: Optional[str]) -> int:
    if not source:
        return 99
    key = source.upper().replace(" ", "_")
    return _ANNOUNCEMENT_SOURCE_PRIORITY.get(key, 50)


def _dedupe_announcements(timeline: List[TimelineEvent]) -> List[TimelineEvent]:
    """같은 날 ANNOUNCEMENT detail 유사도가 높으면 source 우선순위로 1건만 남긴다.

    T2-7 Step 2 — Step 1(로깅만) 이후 데이터 검증 완료되어 실제 병합 활성화.
    알고리즘:
      1) date별 ANNOUNCEMENT 그룹
      2) 그룹 내에서 representative(현재까지 선정된 대표) 대비 유사도 ≥ threshold면 병합
         - source_rank가 더 낮은(우선순위 높은) 쪽을 대표로 승격
      3) 병합되지 않은 이벤트는 그대로 유지
    같은 날이라도 detail이 충분히 다른 공시는 그대로 병렬 노출된다.
    """
    buckets: Dict[str, List[TimelineEvent]] = {}
    others: List[TimelineEvent] = []
    for e in timeline:
        if e.category == "ANNOUNCEMENT":
            buckets.setdefault(e.date.isoformat(), []).append(e)
        else:
            others.append(e)

    kept_announcements: List[TimelineEvent] = []
    for date_key, events in buckets.items():
        if len(events) == 1:
            kept_announcements.extend(events)
            continue
        # 클러스터: 각 요소는 (representative, [members])
        clusters: List[TimelineEvent] = []
        for ev in events:
            matched = False
            for idx, rep in enumerate(clusters):
                if _jaccard_similarity(ev.detail, rep.detail) >= _ANNOUNCEMENT_DEDUP_THRESHOLD:
                    matched = True
                    # 더 우선순위 높은(rank 낮은) 이벤트를 대표로 승격
                    if _announcement_source_rank(ev.source) < _announcement_source_rank(rep.source):
                        logger.debug(
                            "[HistoryAgent] 공시 dedupe 승격: date=%s %s → %s",
                            date_key, rep.source, ev.source,
                        )
                        clusters[idx] = ev
                    break
            if not matched:
                clusters.append(ev)
        if len(clusters) < len(events):
            logger.info(
                "[HistoryAgent] 공시 dedupe: date=%s %d → %d",
                date_key, len(events), len(clusters),
            )
        kept_announcements.extend(clusters)

    return others + kept_announcements


def _dedupe_etf_timeline(events: List[TimelineEvent]) -> List[TimelineEvent]:
    """ETF 분해 시 holding 이벤트와 ETF 자체 이벤트가 (date, title) 기준 중복되면 1건만 남긴다.

    S2-7. SPY/QQQ 같은 ETF 는 상위 보유 종목별 CORPORATE/ANNOUNCEMENT 를 fan-out
    수집한 뒤 ETF 자체 이벤트와 합치는데, 같은 일자·동일 제목으로 두 번 노출되는
    경우가 있다. constituent_ticker 가 명시된 holding 이벤트를 우선 보존 — ETF 자체
    이벤트는 집계라 holding 단위가 더 구체적이다.
    """
    seen: Dict[tuple, TimelineEvent] = {}
    for e in events:
        key = (e.date, e.category, e.title)
        existing = seen.get(key)
        if existing is None:
            seen[key] = e
            continue
        # 둘 다 있을 때: constituent_ticker 명시된 쪽(holding) 우선
        if existing.constituent_ticker is None and e.constituent_ticker is not None:
            seen[key] = e
    return list(seen.values())


# ── 지수 → FRED 매크로 리전 매핑 ────────────────────────────────
_INDEX_REGION: Dict[str, str] = {
    "^IXIC": "US",
    "^GSPC": "US",
    "^DJI":  "US",
    "^KS11": "KR",
}
_DEFAULT_INDEX_REGION = "US"

# ── chart_interval → 이벤트 수집 lookback (§13.4 B) ─────────────
# 봉 단위 차트의 전체 범위에 맞춰 NEWS/MACRO 수집 윈도우를 정렬:
#   1D 일봉(1년 차트) → 1년 / 1W 주봉(3년) → 3년 / 1M 월봉(5년) → 5년
#   1Q 분기봉(20년) → 20년 / 1Y(legacy alias for 1Q) → 20년
_CHART_INTERVAL_LOOKBACK_DAYS: Dict[str, int] = {
    "1D": 365,
    "1W": 1_095,
    "1M": 1_825,
    "1Q": 7_300,
    "1Y": 7_300,
}
_DEFAULT_CHART_INTERVAL_LOOKBACK_DAYS = 365

# ── ETF → FRED 매크로 리전 매핑 ─────────────────────────────────
# 모르는 ETF는 _DEFAULT_INDEX_REGION(US)으로 처리.
_ETF_REGION: Dict[str, str] = {
    "SPY": "US", "QQQ": "US", "IWM": "US", "DIA": "US",
    "VOO": "US", "VTI": "US", "VEA": "US", "VWO": "US",
    "EWY": "KR", "EWJ": "US",  # EWJ는 일본 ETF, MACRO는 US fallback
    "069500": "KR", "229200": "KR",  # KODEX 200, KODEX 코스닥150
}


_ANNOUNCEMENT_SUMMARY_SYSTEM = """\
당신은 SEC 공시 요약 전문가입니다.
8-K 공시 원문을 읽고 핵심 내용을 한국어 2~3문장으로 요약하십시오.

규칙:
- 회사명, 날짜, 금액, 거래 내용 등 핵심 정보를 포함한다
- 투자자가 이해할 수 있는 평이한 한국어를 사용한다
- 요약문만 출력한다. 다른 설명은 추가하지 않는다
"""


async def _summarize_to_korean(detail: str) -> str:
    """영문 8-K 본문을 한국어 2~3문장으로 요약한다. 실패 시 원문 반환."""
    try:
        llm = get_workflow_llm(model=TITLE_MODEL)
        response = await llm.ainvoke([
            SystemMessage(content=_ANNOUNCEMENT_SUMMARY_SYSTEM),
            HumanMessage(content=detail),
        ])
        return response.content.strip()
    except Exception as exc:
        logger.warning("[HistoryAgent] 공시 요약 실패: %s", exc)
        return detail


_ANNOUNCEMENT_SUMMARY_CACHE_VERSION = "v2"
_ANNOUNCEMENT_SUMMARY_CACHE_TTL_SEC = 90 * 24 * 60 * 60  # 90 days


def _announcement_summary_cache_key(detail: str) -> str:
    # 16-hex(64-bit) → 전체 64-hex(256-bit). 이론적 hash collision 영향 0 으로 하한.
    # cross-ticker 캐시 공유 의도(동일 본문 = 동일 요약)는 그대로 유지.
    h = hashlib.sha256(detail.encode()).hexdigest()
    return f"announcement_summary:{_ANNOUNCEMENT_SUMMARY_CACHE_VERSION}:{h}"


async def _enrich_announcement_details(
    timeline: List[TimelineEvent],
    redis: Optional[aioredis.Redis] = None,
) -> None:
    """ANNOUNCEMENT 이벤트의 영문 detail을 한국어 요약으로 교체한다.

    NEWS/MACRO 캐시 패턴(§13.4 B follow-up) 동일 적용:
      announcement_summary:v2:{sha256(detail)} 키로 90일 TTL 영구 보존.
      동일 공시 본문이 여러 ticker/호출에서 등장 시 LLM 호출 0회.
    """
    targets = [
        e for e in timeline
        if e.category == "ANNOUNCEMENT" and needs_korean_summary(e.detail)
    ]
    if not targets:
        return

    cache_keys = [_announcement_summary_cache_key(e.detail) for e in targets]
    cached_values: List[Optional[bytes]] = []
    if redis is not None:
        try:
            cached_values = await redis.mget(cache_keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] 공시 요약 캐시 mget 실패 — miss 로 진행: %s", exc)
            cached_values = [None] * len(targets)
    else:
        cached_values = [None] * len(targets)

    miss_targets: List[TimelineEvent] = []
    miss_originals: List[str] = []
    hit_count = 0
    for event, cached in zip(targets, cached_values):
        if cached is not None:
            summary = cached.decode() if isinstance(cached, (bytes, bytearray)) else str(cached)
            event.detail = summary
            hit_count += 1
        else:
            miss_originals.append(event.detail)
            miss_targets.append(event)

    if not miss_targets:
        logger.info(
            "[HistoryAgent] ✦ 공시 한국어 요약 — 전체 캐시 적중: %d건", hit_count,
        )
        return

    logger.info(
        "[HistoryAgent] ✦ 공시 한국어 요약 시작: %d건 (cache hit=%d, miss=%d)",
        len(targets), hit_count, len(miss_targets),
    )
    summaries = await asyncio.gather(
        *[_summarize_to_korean(e.detail) for e in miss_targets],
        return_exceptions=True,
    )

    save_pairs: List[Tuple[str, str]] = []
    for event, original_detail, summary in zip(miss_targets, miss_originals, summaries):
        if isinstance(summary, Exception):
            logger.warning("[HistoryAgent] 공시 요약 gather 예외: %s", summary)
            continue
        event.detail = summary
        if summary != original_detail:
            save_pairs.append((original_detail, summary))

    if redis is not None and save_pairs:
        try:
            async with redis.pipeline(transaction=False) as pipe:
                for original_detail, summary in save_pairs:
                    pipe.setex(
                        _announcement_summary_cache_key(original_detail),
                        _ANNOUNCEMENT_SUMMARY_CACHE_TTL_SEC,
                        summary,
                    )
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] 공시 요약 캐시 저장 실패 (graceful): %s", exc)

    logger.info("[HistoryAgent] ✦ 공시 한국어 요약 완료")


# §13.4 C — PRICE 카테고리 완전 철거 (2026-04 결정).
# 기존 `_from_price_events`·`_PCT_VALUE_TYPES`·`_EXCLUDED_PRICE_TYPES`·
# `history_price_event_cap`·`price_importance` 는 모두 제거됨.
# 대체: 차트 이상치 봉 마커(/anomaly-bars) + popover 기반 causality.


def _from_corporate_events(result: CorporateEventsResponse) -> List[TimelineEvent]:
    return [
        TimelineEvent(
            title=FALLBACK_TITLE.get(e.type, e.type),
            date=e.date,
            category="CORPORATE",
            type=e.type,
            detail=e.detail,
            source=e.source,
            url=None,
        )
        for e in result.events
    ]


## §17 B2 — _announcement_title 은 service.title_generation_service.announcement_title
## 로 이전됨 (생성자 + 검증자 응집). 호출부는 _from_announcements 에서 announcement_title 사용.


def _from_announcements(
    result: AnnouncementsResponse, ticker_label: Optional[str] = None
) -> List[TimelineEvent]:
    """`ticker_label` 지정 시 title에 prefix 추가. 지정 없으면 기존 fallback."""
    return [
        TimelineEvent(
            title=(
                announcement_title(ticker_label, e.type, e.source)
                if ticker_label
                else FALLBACK_TITLE.get(e.type, e.type)
            ),
            date=e.date,
            category="ANNOUNCEMENT",
            type=e.type,
            detail=e.title,
            source=e.source,
            url=e.url,
            items_str=getattr(e, "items_str", None),
        )
        for e in result.events
    ]


def _from_macro_context(events: List[MacroContextEvent]) -> List[TimelineEvent]:
    # 정책 의미: category="MACRO" 는 "정책/발표(TYPE_A) + 시장 반응(TYPE_B)" 를 모두 포함.
    # related_assets(VIX/Oil/Gold/US10Y/FX) 와 GPR 스파이크는 시장 반응(TYPE_B) 으로
    # 분류기(KR1)가 이후 macro_type 을 채워 구분한다.
    return [
        TimelineEvent(
            title=e.label,
            date=e.date,
            category="MACRO",
            type=e.type,
            detail=e.detail,
            source=e.source,
            change_pct=e.change_pct,
        )
        for e in events
    ]


_PERIOD_DAYS: Dict[str, int] = {
    "1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "5Y": 1825,
}


def datetime_date_from_period(period: str) -> date:
    """period 문자열을 오늘 기준 시작일로 변환. 모르는 값은 90일 fallback."""
    days = _PERIOD_DAYS.get(period.upper(), 90)
    return date.today() - timedelta(days=days)


async def _run_causality(ticker: str, event: TimelineEvent) -> List[HypothesisResult]:
    from app.domains.causality_agent.application.causality_agent_workflow import run_causality_agent

    pre_days, post_days = _causality_window_days()
    start_date = event.date - timedelta(days=pre_days)
    end_date = event.date + timedelta(days=post_days)
    try:
        state = await run_causality_agent(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
        )
        return [HypothesisResult(**h) for h in state.get("hypotheses", [])]
    except Exception as exc:
        logger.warning(
            "[HistoryAgent] causality 분석 실패: ticker=%s, date=%s, type=%s, error=%s",
            ticker, event.date, event.type, exc,
        )
        return []


_INDEX_CAUSALITY_PRE_DAYS = 3   # 이벤트일 기준 이전 며칠 MACRO 스캔
_INDEX_CAUSALITY_POST_DAYS = 1  # 이벤트일 기준 이후 며칠 MACRO 스캔


def _infer_rule_based_index_causality(
    event: TimelineEvent, macro_events: List[TimelineEvent]
) -> List[HypothesisResult]:
    """INDEX SURGE/PLUNGE 이벤트에 ±며칠 내 MACRO 발표를 규칙으로 매핑한다.

    T2-1 Phase A — LLM 없이 결정적 매핑. Phase B(LLM)는 feature flag로 규칙
    미매핑 케이스에만 추가 호출된다.
    """
    pre = timedelta(days=_INDEX_CAUSALITY_PRE_DAYS)
    post = timedelta(days=_INDEX_CAUSALITY_POST_DAYS)
    nearby = [
        m for m in macro_events
        if event.date - pre <= m.date <= event.date + post
    ]
    if not nearby:
        return []

    hypotheses: List[HypothesisResult] = []
    for m in nearby:
        direction = (
            "상승" if (m.change_pct or 0) > 0
            else "하락" if (m.change_pct or 0) < 0
            else "동결"
        )
        day_offset = (m.date - event.date).days
        change_part = f"Δ{m.change_pct:+.2f}%p" if m.change_pct is not None else "변화 없음"
        hypothesis = (
            f"{m.title or m.type} {direction} ({change_part}, D{day_offset:+d}) → "
            f"{event.type}"
        )
        hypotheses.append(HypothesisResult(
            hypothesis=hypothesis,
            supporting_tools_called=["fred:rule_based"],
        ))
    return hypotheses


async def _enrich_causality(ticker: str, timeline: List[TimelineEvent], is_index: bool = False) -> None:
    if is_index:
        # T2-1 Phase A: 근처 MACRO 이벤트를 규칙 기반으로 매핑.
        macro_events = [e for e in timeline if e.category == "MACRO"]
        targets = [
            e for e in timeline
            if e.category == "PRICE"
            and e.type in _CAUSALITY_TRIGGER_TYPES
            and e.causality is None
        ][:_MAX_CAUSALITY_EVENTS]

        if not targets:
            logger.info("[HistoryAgent] ✦ INDEX 인과관계 분석 대상 없음")
            return

        if not macro_events:
            logger.info("[HistoryAgent] ✦ INDEX MACRO 이벤트 없음 — 규칙 기반 causality 건너뜀")
            return

        matched = 0
        unmatched: List[TimelineEvent] = []
        for event in targets:
            hypotheses = _infer_rule_based_index_causality(event, macro_events)
            if hypotheses:
                event.causality = hypotheses
                matched += 1
            else:
                unmatched.append(event)
        logger.info(
            "[HistoryAgent] ✦ INDEX causality Phase A 규칙 매핑: %d/%d (미매핑 %d)",
            matched, len(targets), len(unmatched),
        )

        # T2-1 Phase B: 규칙 미매핑 케이스에만 LLM 워크플로우 호출 (feature flag).
        if unmatched and get_settings().index_causality_llm_enabled:
            try:
                from app.domains.causality_agent.macro.run_macro_causality_agent import (
                    run_macro_causality_agent,
                )
            except ImportError:
                logger.info(
                    "[HistoryAgent] ✦ INDEX causality Phase B 미구현 (macro workflow not found)"
                )
                return

            logger.info(
                "[HistoryAgent] ✦ INDEX causality Phase B(LLM) 시작: %d건", len(unmatched),
            )
            results = await asyncio.gather(
                *[
                    run_macro_causality_agent(ticker, e, timeline)
                    for e in unmatched
                ],
                return_exceptions=True,
            )
            for event, result in zip(unmatched, results):
                if isinstance(result, Exception):
                    logger.warning("[HistoryAgent] Phase B 실패: %s", result)
                    continue
                if result:
                    event.causality = result
        return

    targets = [
        e for e in timeline
        if e.category == "PRICE"
        and e.type in _CAUSALITY_TRIGGER_TYPES
        and e.causality is None
    ][:_MAX_CAUSALITY_EVENTS]

    if not targets:
        logger.info("[HistoryAgent] ✦ 인과관계 분석 대상 없음 (SURGE/PLUNGE 이벤트 없음)")
        return

    logger.info(
        "[HistoryAgent] ✦ 인과관계 분석 시작: %d건 %s",
        len(targets),
        [(e.type, str(e.date)) for e in targets],
    )
    results = await asyncio.gather(
        *[_run_causality(ticker, e) for e in targets],
        return_exceptions=True,
    )

    success = 0
    for event, result in zip(targets, results):
        if isinstance(result, Exception):
            logger.warning("[HistoryAgent] causality gather 예외: %s", result)
            continue
        if result:
            event.causality = result
            success += 1
    logger.info("[HistoryAgent] ✦ 인과관계 분석 완료: %d/%d 성공", success, len(targets))


class HistoryAgentUseCase:

    def __init__(
        self,
        stock_bars_port: StockBarsPort,
        yfinance_corporate_port: YahooFinanceCorporateEventPort,
        dart_corporate_client: DartCorporateEventClient,
        sec_edgar_port: SecEdgarAnnouncementPort,
        dart_announcement_client: DartAnnouncementClient,
        redis: aioredis.Redis,
        enrichment_repo: EventEnrichmentRepositoryPort,
        asset_type_port: AssetTypePort,
        collect_macro_events_uc: Optional[CollectImportantMacroEventsUseCase] = None,
        etf_holdings_port: Optional[EtfHoldingsPort] = None,
        related_assets_port: Optional[RelatedAssetsPort] = None,
        gpr_index_port: Optional[GprIndexPort] = None,
        event_impact_repo: Optional[EventImpactMetricRepositoryPort] = None,
        macro_news_search_port: Optional[MacroNewsSearchPort] = None,
    ):
        self._stock_bars_port = stock_bars_port
        self._yfinance_corporate_port = yfinance_corporate_port
        self._dart_corporate_client = dart_corporate_client
        self._sec_edgar_port = sec_edgar_port
        self._dart_announcement_client = dart_announcement_client
        self._redis = redis
        self._enrichment_repo = enrichment_repo
        self._asset_type_port = asset_type_port
        self._collect_macro_events_uc = collect_macro_events_uc
        self._etf_holdings_port = etf_holdings_port
        self._related_assets_port = related_assets_port
        self._gpr_index_port = gpr_index_port
        self._event_impact_repo = event_impact_repo
        self._macro_news_search_port = macro_news_search_port
        self._event_importance_service = EventImportanceService(enrichment_repo)
        self._event_classifier_service = EventClassifierService(enrichment_repo)

    @staticmethod
    def _build_cache_key(asset_type: str, ticker: str, period: str, enrich_titles: bool) -> str:
        suffix = "" if enrich_titles else ":no-titles"
        return f"history_agent:{_CACHE_VERSION}:{asset_type}:{ticker}:{period}{suffix}"

    async def execute(
        self,
        ticker: str,
        period: str,
        corp_code: Optional[str] = None,
        on_progress: Optional[Callable[[str, str, int], Awaitable[None]]] = None,
        enrich_titles: bool = True,
    ) -> TimelineResponse:
        async def _notify(step: str, label: str, pct: int) -> None:
            if on_progress:
                try:
                    await on_progress(step, label, pct)
                except Exception as exc:
                    logger.warning("[HistoryAgent] on_progress 콜백 예외: %s", exc)

        # asset_type을 먼저 조회해 캐시 키에 포함 — 재분류 시 stale cache 방지.
        quote_type_raw = await self._asset_type_port.get_quote_type(ticker)
        quote_type_upper = (quote_type_raw or "").upper() or "UNKNOWN"
        asset_type = quote_type_upper if quote_type_upper in _SUPPORTED_ASSET_TYPES else quote_type_upper

        cache_key = self._build_cache_key(asset_type, ticker, period, enrich_titles)

        cached = await self._redis.get(cache_key)
        if cached:
            try:
                logger.info(
                    "[HistoryAgent] 캐시 히트: ticker=%s, period=%s, asset_type=%s",
                    ticker, period, asset_type,
                )
                return TimelineResponse.model_validate_json(cached)
            except Exception:
                pass

        logger.info("[HistoryAgent] ══════════════════════════════════════")
        logger.info(
            "[HistoryAgent] 시작: ticker=%s, period=%s, asset_type=%s",
            ticker, period, asset_type,
        )
        logger.info("[HistoryAgent] ══════════════════════════════════════")

        if asset_type == "ETF":
            return await self._execute_etf_timeline(
                ticker=ticker,
                period=period,
                cache_key=cache_key,
                on_progress=on_progress,
                enrich_titles=enrich_titles,
            )

        if asset_type == "INDEX":
            return await self._execute_index_timeline(
                ticker=ticker,
                period=period,
                cache_key=cache_key,
                on_progress=on_progress,
                enrich_titles=enrich_titles,
            )

        if asset_type != "EQUITY":
            # MUTUALFUND / CRYPTOCURRENCY / CURRENCY / UNKNOWN 등은 아직 미지원.
            # 조용히 EQUITY로 처리하던 기존 동작 대신 명시적으로 빈 응답을 반환하고
            # WARNING을 남겨 새 타입이 빠르게 드러나도록 한다.
            logger.warning(
                "[HistoryAgent] 미지원 asset_type — 빈 타임라인 반환: ticker=%s, asset_type=%s",
                ticker, asset_type,
            )
            await _notify("done", "지원하지 않는 자산 유형입니다", 100)
            response = TimelineResponse(
                ticker=ticker,
                chart_interval=period,
                count=0,
                events=[],
                asset_type=asset_type,
            )
            await self._redis.setex(cache_key, _CACHE_TTL, response.model_dump_json())
            return response

        # §13.4 C: PRICE 카테고리 제거 — 가격 이벤트는 차트 이상치 봉 마커로 이동.
        corporate_uc = GetCorporateEventsUseCase(
            yfinance_port=self._yfinance_corporate_port,
            dart_client=self._dart_corporate_client,
        )
        announcement_uc = GetAnnouncementsUseCase(
            sec_edgar_port=self._sec_edgar_port,
            dart_client=self._dart_announcement_client,
        )

        logger.info("[HistoryAgent] [1/4] 데이터 수집 시작 (기업이벤트/공시 병렬)")
        await _notify("data_fetch", "데이터 수집 중...", 10)
        (
            corporate_result, announcement_result,
        ) = await asyncio.gather(
            corporate_uc.execute(ticker=ticker, period=period, corp_code=corp_code),
            announcement_uc.execute(ticker=ticker, period=period, corp_code=corp_code),
            return_exceptions=True,
        )

        timeline: List[TimelineEvent] = []

        if isinstance(corporate_result, CorporateEventsResponse):
            events = _from_corporate_events(corporate_result)
            timeline.extend(events)
            logger.info("[HistoryAgent]   └ 기업 이벤트: %d건", len(events))
        else:
            logger.warning("[HistoryAgent]   └ 기업 이벤트 수집 실패: %s", corporate_result)

        if isinstance(announcement_result, AnnouncementsResponse):
            events = _from_announcements(announcement_result, ticker_label=ticker)
            timeline.extend(events)
            logger.info("[HistoryAgent]   └ 공시: %d건", len(events))
        else:
            logger.warning("[HistoryAgent]   └ 공시 수집 실패: %s", announcement_result)

        logger.info("[HistoryAgent]   └ 타임라인 합계: %d건", len(timeline))

        # T2-7 Step 2 — 같은 날 유사 공시를 source 우선순위(DART > SEC > YAHOO) 기준 1건으로 병합.
        before = len(timeline)
        timeline = _dedupe_announcements(timeline)
        if before != len(timeline):
            logger.info("[HistoryAgent]   └ 공시 dedupe 적용: %d → %d", before, len(timeline))
        timeline.sort(key=lambda e: e.date, reverse=True)

        # 1) DB에서 기존 enrichment 로드
        await _notify("enrichment_load", "캐시 데이터 확인 중...", 35)
        db_map = await self._load_enrichments(ticker, timeline)
        new_events = self._apply_enrichments(ticker, timeline, db_map)
        logger.info(
            "[HistoryAgent] [2/4] DB enrichment 조회: hit=%d, miss=%d",
            len(timeline) - len(new_events), len(new_events),
        )

        # AR 메트릭은 importance prompt에 합류하므로 score() 전에 채운다.
        await self._apply_event_impact_metrics(ticker, timeline)

        # 2) 비-PRICE 타이틀 / 공시 요약 / 분류 / 점수 병렬 실행.
        #    §13.4 C 에서 PRICE 카테고리 제거 — 종목별 SURGE/PLUNGE 인과관계는
        #    /anomaly-bars/{ticker}/{date}/causality 엔드포인트(get_anomaly_causality_usecase)
        #    로 이관됨. _enrich_causality 함수는 격리 단위 테스트만 유지.
        logger.info("[HistoryAgent] [3/4] 타이틀 생성 + 분류 + 점수 (병렬, 신규 이벤트만)")
        await _notify("causality", "타이틀 생성 · 분류 · 점수 중...", 55)

        # v2 분류기는 score_v2 전에 실행 — 재분류된 type을 1~5 점수기 입력으로 사용.
        async def _classify_then_score_v2() -> None:
            await self._event_classifier_service.classify(ticker, timeline)
            await self._event_importance_service.score_v2(ticker, timeline)

        if enrich_titles:
            await asyncio.gather(
                enrich_other_titles(timeline),
                _enrich_announcement_details(timeline, redis=self._redis),
                self._event_importance_service.score(ticker, timeline),
                _classify_then_score_v2(),
            )
        else:
            await asyncio.gather(
                _enrich_announcement_details(timeline, redis=self._redis),
                self._event_importance_service.score(ticker, timeline),
                _classify_then_score_v2(),
            )

        # 4) 신규 이벤트만 DB 저장
        await _notify("saving", "저장 중...", 90)
        await self._save_enrichments(ticker, new_events)
        logger.info("[HistoryAgent] [4/4] 캐시 저장 후 응답 반환")

        response = TimelineResponse(
            ticker=ticker,
            chart_interval=period,
            count=len(timeline),
            events=timeline,
            asset_type=asset_type,
        )
        await self._redis.setex(cache_key, _CACHE_TTL, response.model_dump_json())
        logger.info("[HistoryAgent] 완료: ticker=%s, period=%s, total=%d", ticker, period, len(timeline))
        return response

    async def _execute_index_timeline(
        self,
        ticker: str,
        period: str,
        cache_key: str,
        on_progress: Optional[Callable[[str, str, int], Awaitable[None]]],
        enrich_titles: bool,
    ) -> TimelineResponse:
        async def _notify(step: str, label: str, pct: int) -> None:
            if on_progress:
                try:
                    await on_progress(step, label, pct)
                except Exception:
                    pass

        logger.info("[HistoryAgent] INDEX 경로: 중요 MACRO 수집 시작 (가격·기업이벤트·공시·뉴스 생략)")
        await _notify("data_fetch", "데이터 수집 중...", 10)

        region = _INDEX_REGION.get(ticker, _DEFAULT_INDEX_REGION)
        try:
            macro_events = await self._collect_important_macro_events(
                region=region, period=period,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent]   └ 중요 MACRO 수집 실패 (graceful): %s", exc)
            macro_events = []

        timeline: List[TimelineEvent] = []
        timeline.extend(macro_events)
        logger.info("[HistoryAgent]   └ 중요 MACRO 이벤트: %d건", len(macro_events))

        timeline.sort(key=lambda e: e.date, reverse=True)

        db_map = await self._load_enrichments(ticker, timeline)
        new_events = self._apply_enrichments(ticker, timeline, db_map)
        logger.info(
            "[HistoryAgent] DB enrichment 조회: hit=%d, miss=%d",
            len(timeline) - len(new_events), len(new_events),
        )

        # §13.4 C — INDEX/ETF 도 PRICE 카테고리 제거. 인덱스 인과관계(T2-1 Phase A/B)는
        # 호출되지 않는 상태(_enrich_causality 가 빈 targets 으로 즉시 return). 향후 부활 시
        # /anomaly-bars 엔드포인트로 통일 검토.

        await _notify("title_gen", "AI 타이틀 생성 중...", 70)
        if enrich_titles:
            # 타이틀 먼저 채우고 사유 추정 — Type A cross-ref evidence 가 자연어 타이틀을 참조하기 위함.
            await enrich_macro_titles(timeline, redis=self._redis)
            await enrich_type_b_reasons(
                timeline, redis=self._redis,
                news_search_port=self._macro_news_search_port,
            )
        else:
            # 타이틀 미보강이어도 분류 + cross-ref 만이라도 적용. cutoff 이후 LLM 호출은 자동 skip.
            await enrich_type_b_reasons(
                timeline, redis=self._redis,
                news_search_port=self._macro_news_search_port,
            )

        await self._save_enrichments(ticker, new_events)

        response = TimelineResponse(
            ticker=ticker,
            chart_interval=period,
            count=len(timeline),
            events=timeline,
            asset_type="INDEX",
        )
        await self._redis.setex(cache_key, _CACHE_TTL, response.model_dump_json())
        logger.info("[HistoryAgent] INDEX 완료: ticker=%s, period=%s, total=%d", ticker, period, len(timeline))
        return response

    async def _execute_etf_timeline(
        self,
        ticker: str,
        period: str,
        cache_key: str,
        on_progress: Optional[Callable[[str, str, int], Awaitable[None]]],
        enrich_titles: bool,
    ) -> TimelineResponse:
        """ETF 타임라인 — INDEX 스타일 재사용(PRICE + 지역 MACRO)."""

        async def _notify(step: str, label: str, pct: int) -> None:
            if on_progress:
                try:
                    await on_progress(step, label, pct)
                except Exception as exc:
                    logger.warning("[HistoryAgent] on_progress 콜백 예외: %s", exc)

        region = _ETF_REGION.get(ticker, _DEFAULT_INDEX_REGION)
        logger.info(
            "[HistoryAgent] ETF 경로: ticker=%s, region=%s (PRICE + 중요 MACRO 수집)",
            ticker, region,
        )
        await _notify("data_fetch", "ETF 데이터 수집 중...", 10)

        # §13.4 C: ETF도 PRICE 카테고리 제거 — 이상치 봉 마커로 대체.
        try:
            macro_events = await self._collect_important_macro_events(
                region=region, period=period,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent]   └ ETF 중요 MACRO 수집 실패 (graceful): %s", exc)
            macro_events = []

        timeline: List[TimelineEvent] = []
        timeline.extend(macro_events)
        logger.info("[HistoryAgent]   └ ETF 중요 MACRO 이벤트: %d건", len(macro_events))

        # Holdings 분해 (Step 2). 데이터 없으면 graceful fallback.
        holdings_events: List[TimelineEvent] = []
        if self._etf_holdings_port is not None:
            await _notify("constituents", "ETF 보유종목 이벤트 수집 중...", 40)
            holdings_events = await self._collect_holdings_events(
                etf_ticker=ticker, period=period,
            )
            timeline.extend(holdings_events)
            logger.info(
                "[HistoryAgent]   └ ETF holdings 이벤트: %d건",
                len(holdings_events),
            )

        before_dedupe = len(timeline)
        timeline = _dedupe_etf_timeline(timeline)
        if before_dedupe != len(timeline):
            logger.info(
                "[HistoryAgent]   └ ETF dedupe: %d → %d (holding 분해 + ETF 자체 이벤트 중복 제거)",
                before_dedupe, len(timeline),
            )

        timeline.sort(key=lambda e: e.date, reverse=True)

        db_map = await self._load_enrichments(ticker, timeline)
        new_events = self._apply_enrichments(ticker, timeline, db_map)
        logger.info(
            "[HistoryAgent] ETF DB enrichment 조회: hit=%d, miss=%d",
            len(timeline) - len(new_events), len(new_events),
        )

        await _notify("title_gen", "AI 타이틀 생성 중...", 70)

        # AR 메트릭은 importance prompt 에 합류하므로 score() 전에 채운다.
        # ETF holdings 이벤트는 현재 PR2 스코프에서 BENCHMARK_MISSING 처리되어 None 반환.
        await self._apply_event_impact_metrics(ticker, timeline)

        async def _etf_classify_then_score_v2() -> None:
            await self._event_classifier_service.classify(ticker, timeline)
            await self._event_importance_service.score_v2(ticker, timeline)

        if enrich_titles:
            await asyncio.gather(
                enrich_macro_titles(timeline, redis=self._redis),
                enrich_other_titles(timeline),
                _enrich_announcement_details(timeline, redis=self._redis),
                self._event_importance_service.score(ticker, timeline),
                _etf_classify_then_score_v2(),
            )
        else:
            await asyncio.gather(
                _enrich_announcement_details(timeline, redis=self._redis),
                self._event_importance_service.score(ticker, timeline),
                _etf_classify_then_score_v2(),
            )

        # MACRO 사유 추정은 타이틀 생성 이후 단독 호출 — cross-ref evidence 가 자연어 타이틀 참조.
        await enrich_type_b_reasons(
            timeline, redis=self._redis,
            news_search_port=self._macro_news_search_port,
        )

        await self._save_enrichments(ticker, new_events)

        response = TimelineResponse(
            ticker=ticker,
            chart_interval=period,
            count=len(timeline),
            events=timeline,
            is_etf=True,
            asset_type="ETF",
        )
        await self._redis.setex(cache_key, _CACHE_TTL, response.model_dump_json())
        logger.info(
            "[HistoryAgent] ETF 완료: ticker=%s, period=%s, total=%d, region=%s",
            ticker, period, len(timeline), region,
        )
        return response

    async def _collect_important_macro_events(
        self, *, region: str, period: str
    ) -> List[TimelineEvent]:
        """CollectImportantMacroEventsUseCase로 curated+서프라이즈+스파이크 Top-N 수집.

        usecase 미주입(또는 테스트 환경)이면 MACRO_CONTEXT (related_assets + GPR) fallback.
        정기 FRED 발표는 사용자 분류상 연속적 데이터로 분류되어 제거됨 (시점 명확 이벤트만 유지).
        §13.4 B: chart_interval 봉 단위 차트 범위에 맞춰 lookback_days 명시 전달.
        """
        if self._collect_macro_events_uc is not None:
            lookback_days = _CHART_INTERVAL_LOOKBACK_DAYS.get(
                period.upper(), _DEFAULT_CHART_INTERVAL_LOOKBACK_DAYS,
            )
            try:
                return await self._collect_macro_events_uc.execute(
                    region=region, period=period, lookback_days=lookback_days,
                )
            except Exception as exc:  # noqa: BLE001
                # 실패 원인을 구체적으로 드러내고, aborted transaction을 복구해
                # 이어지는 _load/_save_enrichments 가 InFailedSQLTransactionError로 연쇄 실패하지 않도록 한다.
                logger.warning(
                    "[HistoryAgent] CollectImportantMacroEventsUseCase 실패 — fallback 진입: "
                    "region=%s period=%s error_type=%s error=%s",
                    region, period, type(exc).__name__, exc,
                )
                await self._enrichment_repo.rollback()
                logger.info("[HistoryAgent] fallback 전 세션 롤백 완료")

        macro_window_start = datetime_date_from_period(period)
        macro_window_end = date.today()
        try:
            return await self._collect_macro_context(
                start_date=macro_window_start, end_date=macro_window_end,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] macro context fallback 실패: %s", exc)
            return []

    async def _collect_macro_context(
        self, *, start_date, end_date
    ) -> List[TimelineEvent]:
        """INDEX/ETF용 매크로 컨텍스트 이벤트 수집 (VIX/Oil/Gold/US10Y/FX + GPR).

        수집 결과는 모두 category="MACRO" 로 emit 되지만, 시장 반응(TYPE_B) 성격이라
        이후 macro_classifier 가 macro_type="TYPE_B" 로 분류한다 (정책/발표는 TYPE_A).
        프런트는 이 type 분류로 색상/표시를 분기 (Type A=인디고 / Type B=핑크).
        """
        tasks = []
        if self._related_assets_port is not None:
            tasks.append(
                self._related_assets_port.fetch_significant_moves(
                    start_date=start_date,
                    end_date=end_date,
                    threshold_pct=get_settings().history_related_assets_threshold_pct,
                )
            )
        if self._gpr_index_port is not None:
            tasks.append(
                self._gpr_index_port.fetch_mom_spikes(
                    start_date=start_date,
                    end_date=end_date,
                    mom_change_pct=get_settings().history_gpr_mom_change_pct,
                )
            )
        if not tasks:
            return []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        collected: List[MacroContextEvent] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("[HistoryAgent] macro context 수집 실패: %s", result)
                continue
            collected.extend(result)
        if not collected:
            return []
        events = _from_macro_context(collected)
        logger.info(
            "[HistoryAgent]   └ MACRO_CONTEXT 이벤트: %d건 (related_assets + GPR)",
            len(events),
        )
        return events

    async def _collect_holdings_events(
        self, etf_ticker: str, period: str
    ) -> List[TimelineEvent]:
        """ETF 상위 보유 종목에 대해 CORPORATE/ANNOUNCEMENT 이벤트를 수집한다.

        종목당 yfinance + DART/SEC 외부 호출이 발생하므로 보유 종목 수(N) 와
        동시성(history_holdings_concurrency) 이 응답 시간을 좌우. settings 의
        history_holdings_top_n / history_holdings_concurrency 로 운영 튜닝 가능.
        """
        assert self._etf_holdings_port is not None
        top_n = get_settings().history_holdings_top_n
        holdings = await self._etf_holdings_port.get_top_holdings(etf_ticker, top_n=top_n)
        if not holdings:
            return []

        corporate_uc = GetCorporateEventsUseCase(
            yfinance_port=self._yfinance_corporate_port,
            dart_client=self._dart_corporate_client,
        )
        announcement_uc = GetAnnouncementsUseCase(
            sec_edgar_port=self._sec_edgar_port,
            dart_client=self._dart_announcement_client,
        )

        # A-2: 종목당 CORP+ANN 동시 fan-out을 제한해 yfinance/DART/SEC 429 가속 방지.
        sem = asyncio.Semaphore(get_settings().history_holdings_concurrency)

        async def _fetch(h):
            async with sem:
                corp, ann = await asyncio.gather(
                    corporate_uc.execute(ticker=h.ticker, period=period),
                    announcement_uc.execute(ticker=h.ticker, period=period),
                    return_exceptions=True,
                )
            events: List[TimelineEvent] = []
            if isinstance(corp, CorporateEventsResponse):
                for e in _from_corporate_events(corp):
                    e.constituent_ticker = h.ticker
                    e.weight_pct = h.weight_pct
                    e.source = f"{etf_ticker}:{e.source or 'CORP'}"
                    events.append(e)
            if isinstance(ann, AnnouncementsResponse):
                for e in _from_announcements(ann, ticker_label=h.ticker):
                    e.constituent_ticker = h.ticker
                    e.weight_pct = h.weight_pct
                    e.source = f"{etf_ticker}:{e.source or 'ANN'}"
                    events.append(e)
            return events

        results = await asyncio.gather(
            *[_fetch(h) for h in holdings], return_exceptions=True
        )
        collected: List[TimelineEvent] = []
        for holding, result in zip(holdings, results):
            if isinstance(result, Exception):
                logger.warning(
                    "[HistoryAgent] constituent %s 이벤트 수집 실패: %s",
                    holding.ticker, result,
                )
                continue
            collected.extend(result)
        return collected

    async def _apply_event_impact_metrics(
        self, ticker: str, timeline: List[TimelineEvent]
    ) -> None:
        """event_impact_metrics 의 5d/20d AR을 timeline 이벤트에 in-place 주입.

        - repo 미주입(테스트 환경 등) 또는 timeline 빈 경우 no-op
        - status="OK" 메트릭만 abnormal_return_*d 채움. 다른 status 는 ar_status 만 기록
        - 같은 (ticker,date,type,detail_hash) 의 5d/20d 행 두 개를 한번에 매핑
        """
        if self._event_impact_repo is None or not timeline:
            return

        keys = [
            (
                ticker,
                e.date,
                e.type,
                compute_detail_hash(e.detail, e.constituent_ticker),
            )
            for e in timeline
        ]
        try:
            metrics = await self._event_impact_repo.find_by_event_keys(keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[HistoryAgent] event_impact 조회 실패 (graceful, AR 미주입): %s", exc,
            )
            return

        # (ticker, date, type, detail_hash) → {post_days: metric}
        by_key: Dict[Tuple[str, date, str, str], Dict[int, EventImpactMetric]] = {}
        for m in metrics:
            k = (m.ticker, m.event_date, m.event_type, m.detail_hash)
            by_key.setdefault(k, {})[m.post_days] = m

        applied = 0
        for event in timeline:
            k = (
                ticker,
                event.date,
                event.type,
                compute_detail_hash(event.detail, event.constituent_ticker),
            )
            windows = by_key.get(k)
            if not windows:
                continue
            applied += 1
            # 5d / 20d AR — status="OK" 인 행만 값 노출
            m5 = windows.get(5)
            m20 = windows.get(20)
            if m5 and m5.status == "OK":
                event.abnormal_return_5d = m5.abnormal_return_pct
            if m20 and m20.status == "OK":
                event.abnormal_return_20d = m20.abnormal_return_pct
            # 5d 우선으로 status/benchmark 결정 (없으면 20d)
            primary = m5 or m20
            if primary:
                event.ar_status = primary.status
                if primary.benchmark_ticker:
                    event.benchmark_ticker = primary.benchmark_ticker
        if applied:
            logger.info(
                "[HistoryAgent] AR 메트릭 적용: ticker=%s applied=%d/%d",
                ticker, applied, len(timeline),
            )

    async def _load_enrichments(
        self, ticker: str, timeline: List[TimelineEvent]
    ) -> Dict[Tuple, "EventEnrichment"]:
        # title/causality는 v1 행에서만 로드(v2 행은 reclassified_type 캐시 용도).
        keys = [
            (
                ticker,
                e.date,
                e.type,
                compute_detail_hash(e.detail, e.constituent_ticker),
                "v1",
            )
            for e in timeline
        ]
        try:
            enrichments = await self._enrichment_repo.find_by_keys(keys)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[HistoryAgent] _load_enrichments 실패 — 빈 캐시로 진행: "
                "ticker=%s keys=%d error_type=%s error=%s",
                ticker, len(keys), type(exc).__name__, exc,
            )
            await self._enrichment_repo.rollback()
            return {}
        return {
            (e.ticker, e.event_date, e.event_type, e.detail_hash): e
            for e in enrichments
        }

    def _apply_enrichments(
        self,
        ticker: str,
        timeline: List[TimelineEvent],
        db_map: Dict,
    ) -> List[TimelineEvent]:
        new_events = []
        for event in timeline:
            key = (
                ticker,
                event.date,
                event.type,
                compute_detail_hash(event.detail, event.constituent_ticker),
            )
            enrichment = db_map.get(key)
            # 옛 backend가 ANNOUNCEMENT에 _announcement_title()의 raw form을 그대로 캐시한 경우
            # cache hit이라도 LLM 재처리 + DB 갱신 대상으로 들어가도록 stale 판정.
            is_stale_pseudo = (
                enrichment is not None
                and event.category == "ANNOUNCEMENT"
                and is_pseudo_announcement_title_str(enrichment.title)
            )
            if enrichment and not is_stale_pseudo:
                event.title = enrichment.title
                if enrichment.causality:
                    event.causality = [HypothesisResult(**h) for h in enrichment.causality]
            else:
                new_events.append(event)
        return new_events

    async def _save_enrichments(self, ticker: str, events: List[TimelineEvent]) -> None:
        if not events:
            return
        enrichments = [
            EventEnrichment(
                ticker=ticker,
                event_date=e.date,
                event_type=e.type,
                detail_hash=compute_detail_hash(e.detail, e.constituent_ticker),
                title=e.title,
                causality=(
                    [h.model_dump() for h in e.causality] if e.causality else None
                ),
                importance_score=e.importance_score,
                items_str=e.items_str,
                classifier_version="v1",
            )
            for e in events
        ]
        try:
            saved = await self._enrichment_repo.upsert_bulk(enrichments)
            logger.info("[HistoryAgent] DB enrichment 저장: %d건", saved)
        except Exception as exc:  # noqa: BLE001
            # DB 스키마 미일치/트랜잭션 abort 시에도 응답 자체는 돌려주기 위해 graceful degradation.
            logger.error(
                "[HistoryAgent] DB enrichment 저장 실패 (응답은 정상 반환): "
                "ticker=%s events=%d error_type=%s error=%s",
                ticker, len(enrichments), type(exc).__name__, exc,
            )
            await self._enrichment_repo.rollback()
