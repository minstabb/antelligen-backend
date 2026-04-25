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
from app.domains.dashboard.application.port.out.fred_macro_port import FredMacroPort
from app.domains.dashboard.application.port.out.sec_edgar_announcement_port import (
    SecEdgarAnnouncementPort,
)
from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.application.port.out.yfinance_corporate_event_port import (
    YahooFinanceCorporateEventPort,
)
from app.domains.dashboard.application.response.announcement_response import AnnouncementsResponse
from app.domains.dashboard.application.response.corporate_event_response import CorporateEventsResponse
from app.domains.dashboard.application.response.economic_event_response import EconomicEventsResponse
from app.domains.dashboard.application.usecase.get_announcements_usecase import (
    GetAnnouncementsUseCase,
)
from app.domains.dashboard.application.usecase.get_corporate_events_usecase import (
    GetCorporateEventsUseCase,
)
from app.domains.dashboard.application.usecase.get_economic_events_usecase import (
    GetEconomicEventsUseCase,
)
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
)
from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.application.port.out.fundamentals_event_port import (
    FundamentalEvent,
    FundamentalsEventPort,
)
from app.domains.history_agent.application.port.out.news_event_port import (
    NewsEventPort,
    NewsItem,
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
from app.domains.history_agent.application.service.text_utils import (
    needs_korean_summary,
    needs_news_korean_translation,
)
from app.domains.history_agent.application.service.title_generation_service import (
    FALLBACK_TITLE,
    TITLE_MODEL,
    batch_titles,
    enrich_macro_titles,
    enrich_other_titles,
    is_fallback_title,
)
from app.domains.history_agent.domain.entity.event_enrichment import (
    EventEnrichment,
    compute_detail_hash,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

_CACHE_TTL = 3600
# v3: 뉴스 카테고리(NEWS) + news-sentiment 필드 추가로 스키마 변경 — v2 캐시 무효화.
_CACHE_VERSION = "v3"

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


async def _enrich_announcement_details(timeline: List[TimelineEvent]) -> None:
    """ANNOUNCEMENT 이벤트의 영문 detail을 한국어 요약으로 교체한다."""
    targets = [
        e for e in timeline
        if e.category == "ANNOUNCEMENT" and needs_korean_summary(e.detail)
    ]
    if not targets:
        return

    logger.info("[HistoryAgent] ✦ 공시 한국어 요약 시작: %d건", len(targets))
    summaries = await asyncio.gather(
        *[_summarize_to_korean(e.detail) for e in targets],
        return_exceptions=True,
    )

    for event, summary in zip(targets, summaries):
        if isinstance(summary, Exception):
            logger.warning("[HistoryAgent] 공시 요약 gather 예외: %s", summary)
            continue
        event.detail = summary
    logger.info("[HistoryAgent] ✦ 공시 한국어 요약 완료")


_NEWS_SUMMARY_BATCH_SYSTEM = """\
당신은 금융 뉴스 요약 전문가입니다.
영문 기사 제목/요약 목록을 입력받아 각 항목을 한국어 1문장(40자 이내)으로 간결히 요약하십시오.

규칙:
- 종목·핵심 사건·영향을 담되 과장·추측 금지
- 숫자, 고유명사는 원문 그대로 유지
- 입력 항목 수와 정확히 동일한 개수의 요약을 반환
- JSON 배열로만 응답: ["요약1", "요약2", ...]
- 추가 설명·머리글·코드 펜스 금지
"""


_NEWS_SUMMARY_CACHE_VERSION = "v1"
_NEWS_SUMMARY_CACHE_TTL_SEC = 90 * 24 * 60 * 60  # 90 days


def _news_summary_cache_key(title: str) -> str:
    h = hashlib.sha256(title.encode()).hexdigest()[:16]
    return f"news_summary:{_NEWS_SUMMARY_CACHE_VERSION}:{h}"


async def _enrich_news_details(
    timeline: List[TimelineEvent],
    redis: Optional[aioredis.Redis] = None,
) -> None:
    """NEWS 이벤트의 영문 title/detail을 한국어 요약 한 문장으로 동시에 교체한다.

    - needs_news_korean_translation 판정(영문·10자 이상) 통과한 항목만 요약 대상
    - title과 detail은 동일 요약문으로 교체 (UI 카드의 제목/본문 일관성 유지)
    - feature flag: history_news_korean_summary_enabled (기본 True)
    - §13.4 B follow-up #1: 단건 ainvoke × N → batch_titles 1+ batch
    - §13.4 B follow-up #2 (이 변경): Redis 캐시(news_summary:v1:{sha256(title)[:16]})
      로 영문 title 별 요약 영구 보존. 동일 NEWS 가 여러 ticker/호출에서 등장 시
      LLM 호출 0회. TTL 90일.
    """
    if not get_settings().history_news_korean_summary_enabled:
        return

    targets = [
        e for e in timeline
        if e.category == "NEWS" and needs_news_korean_translation(e.title)
    ]
    if not targets:
        return

    cache_keys = [_news_summary_cache_key(e.title) for e in targets]
    cached_values: List[Optional[bytes]] = []
    if redis is not None:
        try:
            cached_values = await redis.mget(cache_keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] 뉴스 요약 캐시 mget 실패 — miss 로 진행: %s", exc)
            cached_values = [None] * len(targets)
    else:
        cached_values = [None] * len(targets)

    miss_targets: List[TimelineEvent] = []
    miss_originals: List[str] = []
    hit_count = 0
    for event, cached in zip(targets, cached_values):
        if cached is not None:
            summary = cached.decode() if isinstance(cached, (bytes, bytearray)) else str(cached)
            event.title = summary
            event.detail = summary
            hit_count += 1
        else:
            miss_originals.append(event.title)
            miss_targets.append(event)

    if not miss_targets:
        logger.info(
            "[HistoryAgent] ✦ 뉴스 한국어 요약 — 전체 캐시 적중: %d건", hit_count,
        )
        return

    logger.info(
        "[HistoryAgent] ✦ 뉴스 한국어 요약 시작: %d건 (cache hit=%d, miss=%d)",
        len(targets), hit_count, len(miss_targets),
    )
    summaries = await batch_titles(
        items=miss_targets,
        system_prompt=_NEWS_SUMMARY_BATCH_SYSTEM,
        build_line=lambda e: e.title,
        get_fallback=lambda e: e.title,
        batch_size=get_settings().history_news_summary_batch_size,
    )
    save_pairs: List[Tuple[str, str]] = []
    for event, original_title, summary in zip(miss_targets, miss_originals, summaries):
        if not summary:
            continue
        event.title = summary
        event.detail = summary
        if summary != original_title:
            save_pairs.append((original_title, summary))

    if redis is not None and save_pairs:
        try:
            async with redis.pipeline(transaction=False) as pipe:
                for original_title, summary in save_pairs:
                    pipe.setex(
                        _news_summary_cache_key(original_title),
                        _NEWS_SUMMARY_CACHE_TTL_SEC,
                        summary,
                    )
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] 뉴스 요약 캐시 저장 실패 (graceful): %s", exc)

    logger.info("[HistoryAgent] ✦ 뉴스 한국어 요약 완료")


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


def _announcement_title(ticker: str, event_type: str, source: str) -> str:
    """ANNOUNCEMENT fallback title에 기업명/식별자 prefix를 붙여 같은 날 여러 공시가
    동일한 "주요 공시" 제목으로 붙어 UI에서 중복처럼 보이는 문제를 해결한다(§17 B2).

    - 미국 8-K (sec_edgar): "{ticker} 8-K"
    - 한국 DART: "{ticker} 주요 공시"
    - 기타: 기존 fallback 유지
    """
    if not ticker:
        return FALLBACK_TITLE.get(event_type, event_type)
    if source and "sec_edgar" in source.lower():
        return f"{ticker} 8-K"
    if source and "dart" in source.lower():
        return f"{ticker} 주요 공시"
    return f"{ticker} {FALLBACK_TITLE.get(event_type, event_type)}"


def _from_announcements(
    result: AnnouncementsResponse, ticker_label: Optional[str] = None
) -> List[TimelineEvent]:
    """`ticker_label` 지정 시 title에 prefix 추가. 지정 없으면 기존 fallback."""
    return [
        TimelineEvent(
            title=(
                _announcement_title(ticker_label, e.type, e.source)
                if ticker_label
                else FALLBACK_TITLE.get(e.type, e.type)
            ),
            date=e.date,
            category="ANNOUNCEMENT",
            type=e.type,
            detail=e.title,
            source=e.source,
            url=e.url,
        )
        for e in result.events
    ]


def _from_news_items(items: List[NewsItem]) -> List[TimelineEvent]:
    """NewsEventPort 결과를 TimelineEvent로 변환.

    source 필드는 `news:{provider}` 형식(예: `news:finnhub`)으로 UI 뱃지 구분.
    title은 우선 원문 제목을 그대로 두고, 타이틀 enrich 단계에서 대체될 수 있다.
    """
    events: List[TimelineEvent] = []
    for item in items:
        if not item.title:
            continue
        title = item.title.strip()
        events.append(
            TimelineEvent(
                title=title[:200],
                date=item.date,
                category="NEWS",
                type="NEWS",
                detail=(item.summary or item.title).strip()[:600],
                source=f"news:{item.source}",
                url=item.url or None,
                sentiment=item.sentiment,
            )
        )
    return events


def _from_fundamentals(events: List[FundamentalEvent], ticker: str) -> List[TimelineEvent]:
    return [
        TimelineEvent(
            title=FALLBACK_TITLE.get(e.type, e.type),
            date=e.date,
            category="CORPORATE",
            type=e.type,
            detail=e.detail,
            source=e.source,
            change_pct=e.change_pct,
        )
        for e in events
    ]


def _from_macro_context(events: List[MacroContextEvent]) -> List[TimelineEvent]:
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


_KR_TICKER_PATTERN = __import__("re").compile(r"^\d{6}$")


_PERIOD_DAYS: Dict[str, int] = {
    "1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "5Y": 1825,
}


def datetime_date_from_period(period: str) -> date:
    """period 문자열을 오늘 기준 시작일로 변환. 모르는 값은 90일 fallback."""
    days = _PERIOD_DAYS.get(period.upper(), 90)
    return date.today() - timedelta(days=days)


def _resolve_equity_region(ticker: str) -> str:
    if _KR_TICKER_PATTERN.match(ticker):
        return "KR"
    return "US"


def _from_macro_events(result: EconomicEventsResponse) -> List[TimelineEvent]:
    events = []
    for e in result.events:
        if e.previous is not None:
            change = round(e.value - e.previous, 4)
            sign = "+" if change >= 0 else ""
            detail = f"{e.label} {e.value:.2f}% (이전: {e.previous:.2f}%, 변화: {sign}{change:.2f}%p)"
            change_pct = change
        else:
            detail = f"{e.label} {e.value:.2f}%"
            change_pct = None
        events.append(
            TimelineEvent(
                title=FALLBACK_TITLE.get(e.type, e.label),
                date=e.date,
                category="MACRO",
                type=e.type,
                detail=detail,
                source="FRED",
                change_pct=change_pct,
            )
        )
    return events


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
        fred_macro_port: FredMacroPort,
        collect_macro_events_uc: Optional[CollectImportantMacroEventsUseCase] = None,
        etf_holdings_port: Optional[EtfHoldingsPort] = None,
        news_port: Optional[NewsEventPort] = None,
        fundamentals_port: Optional[FundamentalsEventPort] = None,
        related_assets_port: Optional[RelatedAssetsPort] = None,
        gpr_index_port: Optional[GprIndexPort] = None,
    ):
        self._stock_bars_port = stock_bars_port
        self._yfinance_corporate_port = yfinance_corporate_port
        self._dart_corporate_client = dart_corporate_client
        self._sec_edgar_port = sec_edgar_port
        self._dart_announcement_client = dart_announcement_client
        self._redis = redis
        self._enrichment_repo = enrichment_repo
        self._asset_type_port = asset_type_port
        self._fred_macro_port = fred_macro_port
        self._collect_macro_events_uc = collect_macro_events_uc
        self._etf_holdings_port = etf_holdings_port
        self._news_port = news_port
        self._fundamentals_port = fundamentals_port
        self._related_assets_port = related_assets_port
        self._gpr_index_port = gpr_index_port

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
                period=period,
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

        logger.info("[HistoryAgent] [1/4] 데이터 수집 시작 (기업이벤트/공시/뉴스/fundamentals 병렬)")
        await _notify("data_fetch", "데이터 수집 중...", 10)
        region = _resolve_equity_region(ticker)
        (
            corporate_result, announcement_result,
            news_events, fundamentals_events,
        ) = await asyncio.gather(
            corporate_uc.execute(ticker=ticker, period=period, corp_code=corp_code),
            announcement_uc.execute(ticker=ticker, period=period, corp_code=corp_code),
            self._collect_news_events(ticker=ticker, period=period, region=region),
            self._collect_fundamentals(ticker=ticker, period=period),
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

        if isinstance(news_events, list):
            timeline.extend(news_events)
        else:
            logger.warning("[HistoryAgent]   └ 뉴스 수집 실패 (graceful): %s", news_events)

        if isinstance(fundamentals_events, list):
            timeline.extend(fundamentals_events)
        else:
            logger.warning("[HistoryAgent]   └ fundamentals 수집 실패 (graceful): %s", fundamentals_events)

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

        # 2) causality / 비-PRICE 타이틀 / 공시 요약을 병렬 실행.
        #    §13.4 C에서 PRICE 카테고리가 제거되어 price_titles 체인은 불필요.
        logger.info("[HistoryAgent] [3/4] 인과관계 + 타이틀 생성 (병렬, 신규 이벤트만)")
        await _notify("causality", "인과관계 분석 · 타이틀 생성 중...", 55)

        causality_task = _enrich_causality(ticker, timeline)

        if enrich_titles:
            await asyncio.gather(
                causality_task,
                enrich_other_titles(timeline),
                _enrich_announcement_details(timeline),
                _enrich_news_details(timeline, redis=self._redis),
            )
        else:
            await asyncio.gather(
                causality_task,
                _enrich_announcement_details(timeline),
                _enrich_news_details(timeline, redis=self._redis),
            )

        # 4) 신규 이벤트만 DB 저장
        await _notify("saving", "저장 중...", 90)
        await self._save_enrichments(ticker, new_events)
        logger.info("[HistoryAgent] [4/4] 캐시 저장 후 응답 반환")

        response = TimelineResponse(
            ticker=ticker,
            period=period,
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

        logger.info("[HistoryAgent] INDEX 경로: 중요 MACRO + 뉴스 수집 시작 (가격·기업이벤트·공시 생략)")
        await _notify("data_fetch", "데이터 수집 중...", 10)

        region = _INDEX_REGION.get(ticker, _DEFAULT_INDEX_REGION)
        (
            macro_events, news_events,
        ) = await asyncio.gather(
            self._collect_important_macro_events(region=region, period=period),
            self._collect_news_events(ticker=ticker, period=period, region="GLOBAL"),
            return_exceptions=True,
        )

        timeline: List[TimelineEvent] = []
        if isinstance(macro_events, list):
            timeline.extend(macro_events)
            logger.info("[HistoryAgent]   └ 중요 MACRO 이벤트: %d건", len(macro_events))
        else:
            logger.warning("[HistoryAgent]   └ 중요 MACRO 수집 실패 (graceful): %s", macro_events)

        if isinstance(news_events, list):
            timeline.extend(news_events)
        else:
            logger.warning("[HistoryAgent]   └ 뉴스 수집 실패 (graceful): %s", news_events)

        timeline.sort(key=lambda e: e.date, reverse=True)

        db_map = await self._load_enrichments(ticker, timeline)
        new_events = self._apply_enrichments(ticker, timeline, db_map)
        logger.info(
            "[HistoryAgent] DB enrichment 조회: hit=%d, miss=%d",
            len(timeline) - len(new_events), len(new_events),
        )

        await _enrich_causality(ticker, timeline, is_index=True)

        await _notify("title_gen", "AI 타이틀 생성 중...", 70)
        if enrich_titles:
            await asyncio.gather(
                enrich_macro_titles(timeline, redis=self._redis),
                _enrich_news_details(timeline, redis=self._redis),
            )
        else:
            await _enrich_news_details(timeline, redis=self._redis)

        await self._save_enrichments(ticker, new_events)

        response = TimelineResponse(
            ticker=ticker,
            period=period,
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
        (
            macro_events, news_events,
        ) = await asyncio.gather(
            self._collect_important_macro_events(region=region, period=period),
            self._collect_news_events(ticker=ticker, period=period, region="GLOBAL"),
            return_exceptions=True,
        )

        timeline: List[TimelineEvent] = []
        if isinstance(macro_events, list):
            timeline.extend(macro_events)
            logger.info("[HistoryAgent]   └ ETF 중요 MACRO 이벤트: %d건", len(macro_events))
        else:
            logger.warning("[HistoryAgent]   └ ETF 중요 MACRO 수집 실패 (graceful): %s", macro_events)

        if isinstance(news_events, list):
            timeline.extend(news_events)
        else:
            logger.warning("[HistoryAgent]   └ 뉴스 수집 실패 (graceful): %s", news_events)

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

        timeline.sort(key=lambda e: e.date, reverse=True)

        db_map = await self._load_enrichments(ticker, timeline)
        new_events = self._apply_enrichments(ticker, timeline, db_map)
        logger.info(
            "[HistoryAgent] ETF DB enrichment 조회: hit=%d, miss=%d",
            len(timeline) - len(new_events), len(new_events),
        )

        await _notify("title_gen", "AI 타이틀 생성 중...", 70)
        if enrich_titles:
            await asyncio.gather(
                enrich_macro_titles(timeline, redis=self._redis),
                enrich_other_titles(timeline),
                _enrich_announcement_details(timeline),
                _enrich_news_details(timeline, redis=self._redis),
            )
        else:
            await asyncio.gather(
                _enrich_announcement_details(timeline),
                _enrich_news_details(timeline, redis=self._redis),
            )

        await self._save_enrichments(ticker, new_events)

        response = TimelineResponse(
            ticker=ticker,
            period=period,
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

        usecase 미주입(또는 테스트 환경)이면 구버전 MACRO + MACRO_CONTEXT fallback 경로를 유지한다.
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
        fred_region = region if region in {"US", "KR"} else "US"
        macro_result, macro_context = await asyncio.gather(
            GetEconomicEventsUseCase(fred_macro_port=self._fred_macro_port).execute(
                period=period if period.upper() in {"1D", "1W", "1M", "1Y"} else "1Y",
                region=fred_region,
            ),
            self._collect_macro_context(
                start_date=macro_window_start, end_date=macro_window_end,
            ),
            return_exceptions=True,
        )
        result: List[TimelineEvent] = []
        if isinstance(macro_result, EconomicEventsResponse):
            result.extend(_from_macro_events(macro_result))
        if isinstance(macro_context, list):
            result.extend(macro_context)
        return result

    async def _collect_fundamentals(
        self, *, ticker: str, period: str
    ) -> List[TimelineEvent]:
        """애널리스트 레이팅 변동 · 실적 서프라이즈를 CORPORATE 이벤트로 변환."""
        if self._fundamentals_port is None:
            return []
        try:
            events = await self._fundamentals_port.fetch_events(
                ticker=ticker, period=period,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] fundamentals 수집 실패: %s", exc)
            return []
        if not events:
            return []
        result = _from_fundamentals(events, ticker)
        logger.info(
            "[HistoryAgent]   └ FUNDAMENTALS 이벤트: %d건 (analyst/earnings)",
            len(result),
        )
        return result

    async def _collect_macro_context(
        self, *, start_date, end_date
    ) -> List[TimelineEvent]:
        """INDEX/ETF용 매크로 컨텍스트 이벤트 수집 (VIX/Oil/Gold/US10Y/FX + GPR)."""
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

    async def _collect_news_events(
        self, *, ticker: str, period: str, region: str
    ) -> List[TimelineEvent]:
        """NewsEventPort로 뉴스를 수집해 TimelineEvent 로 변환.

        포트가 주입되지 않았거나 실패해도 빈 리스트를 반환해 graceful degradation.
        §13.4 B: chart_interval 봉 단위 차트 범위에 맞춰 lookback_days 명시 전달.
        """
        if self._news_port is None:
            return []
        top_n = get_settings().history_news_top_n
        lookback_days = _CHART_INTERVAL_LOOKBACK_DAYS.get(
            period.upper(), _DEFAULT_CHART_INTERVAL_LOOKBACK_DAYS,
        )
        try:
            items = await self._news_port.fetch_news(
                ticker=ticker, period=period, region=region, top_n=top_n,  # type: ignore[arg-type]
                lookback_days=lookback_days,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HistoryAgent] 뉴스 수집 실패: %s", exc)
            return []
        events = _from_news_items(items)
        logger.info(
            "[HistoryAgent]   └ NEWS 이벤트: %d건 (region=%s, sources=%s)",
            len(events), region,
            sorted({e.source for e in events if e.source}),
        )
        return events

    async def _collect_holdings_events(
        self, etf_ticker: str, period: str
    ) -> List[TimelineEvent]:
        """ETF 상위 보유 종목에 대해 CORPORATE/ANNOUNCEMENT 이벤트를 수집한다."""
        assert self._etf_holdings_port is not None
        holdings = await self._etf_holdings_port.get_top_holdings(etf_ticker, top_n=5)
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

    async def _load_enrichments(
        self, ticker: str, timeline: List[TimelineEvent]
    ) -> Dict[Tuple, "EventEnrichment"]:
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
            enrichments = await self._enrichment_repo.find_by_keys(keys)
        except Exception as exc:  # noqa: BLE001
            # DB 스키마 미일치/트랜잭션 abort 상태에서 빈 캐시로 계속 진행하도록 한다.
            # 없으면 _apply_enrichments가 모든 이벤트를 '신규'로 간주해 LLM 단계만 실행된다.
            logger.error(
                "[HistoryAgent] _load_enrichments 실패 — 빈 캐시로 진행: "
                "ticker=%s keys=%d error_type=%s error=%s",
                ticker, len(keys), type(exc).__name__, exc,
            )
            await self._enrichment_repo.rollback()
            return {}
        return {(e.ticker, e.event_date, e.event_type, e.detail_hash): e for e in enrichments}

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
            if enrichment:
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
