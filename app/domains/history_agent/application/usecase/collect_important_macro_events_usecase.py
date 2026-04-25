"""INDEX/ETF·매크로 전용 타임라인에서 공통으로 쓰는 매크로 이벤트 수집 유스케이스.

큐레이션된 역사적 이벤트 + 서프라이즈 FRED + 관련자산 스파이크 + GPR 스파이크를 병렬 수집 후
LLM 중요도 랭커로 스코어링하고 Top-N만 반환한다.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Awaitable, Callable, List, Optional

from app.domains.dashboard.application.port.out.fred_macro_port import FredMacroPort
from app.domains.dashboard.application.response.economic_event_response import (
    EconomicEventsResponse,
)
from app.domains.dashboard.application.usecase.get_economic_events_usecase import (
    GetEconomicEventsUseCase,
)
from app.domains.history_agent.application.port.out.curated_macro_events_port import (
    CuratedMacroEventsPort,
)
from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.application.port.out.related_assets_port import (
    GprIndexPort,
    MacroContextEvent,
    RelatedAssetsPort,
)
from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.macro_importance_ranker import (
    MacroImportanceRanker,
)
from app.domains.history_agent.application.service.title_generation_service import (
    FALLBACK_TITLE,
)
from app.domains.history_agent.domain.entity.curated_macro_event import CuratedMacroEvent
from app.infrastructure.config.settings import get_settings

ProgressCallback = Callable[[str, str, int], Awaitable[None]]

logger = logging.getLogger(__name__)


_PERIOD_DAYS = {
    "1W": 7, "1M": 30, "3M": 90, "6M": 180,
    "1Y": 365, "2Y": 730, "5Y": 1825, "10Y": 3650,
}


def _period_to_start_date(period: str) -> date:
    days = _PERIOD_DAYS.get(period.upper(), 365)
    return date.today() - timedelta(days=days)


def _from_curated(event: CuratedMacroEvent) -> TimelineEvent:
    return TimelineEvent(
        title=event.title,
        date=event.date,
        category="MACRO",
        type=event.event_type,
        detail=event.detail,
        source=f"curated:{event.region}",
        url=event.source_url,
        importance_score=event.importance_score,
    )


def _from_fred_response(result: EconomicEventsResponse) -> List[TimelineEvent]:
    events: List[TimelineEvent] = []
    for e in result.events:
        if e.previous is not None:
            change = round(e.value - e.previous, 4)
            sign = "+" if change >= 0 else ""
            detail = (
                f"{e.label} {e.value:.2f}% (이전: {e.previous:.2f}%, "
                f"변화: {sign}{change:.2f}%p)"
            )
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


def _dedupe(events: List[TimelineEvent]) -> List[TimelineEvent]:
    """같은 (date, type, detail prefix) 쌍은 curated > FRED > context 우선순위로 1건만 남긴다."""
    def rank(ev: TimelineEvent) -> int:
        if ev.source and ev.source.startswith("curated"):
            return 0
        if ev.source == "FRED":
            return 1
        return 2

    buckets: dict[tuple, TimelineEvent] = {}
    for event in events:
        key = (event.date, event.type)
        existing = buckets.get(key)
        if existing is None or rank(event) < rank(existing):
            buckets[key] = event
    return list(buckets.values())


class CollectImportantMacroEventsUseCase:

    def __init__(
        self,
        fred_macro_port: FredMacroPort,
        curated_port: CuratedMacroEventsPort,
        related_assets_port: Optional[RelatedAssetsPort],
        gpr_index_port: Optional[GprIndexPort],
        enrichment_repo: EventEnrichmentRepositoryPort,
    ):
        self._fred = fred_macro_port
        self._curated = curated_port
        self._related = related_assets_port
        self._gpr = gpr_index_port
        self._enrichment_repo = enrichment_repo
        self._ranker = MacroImportanceRanker(enrichment_repo)

    async def execute(
        self,
        *,
        region: str,
        period: str,
        top_n: Optional[int] = None,
        on_progress: Optional[ProgressCallback] = None,
        lookback_days: Optional[int] = None,
    ) -> List[TimelineEvent]:
        """매크로 이벤트를 수집한다.

        `lookback_days` 가 주어지면 `_PERIOD_DAYS[period]` 보다 우선 적용 (§13.4 B).
        chart_interval 기반 timeline 호출은 봉 단위 차트 범위에 맞는 윈도우를
        명시적으로 전달해야 한다 (예: 1D=365, 1W=1095, 1M=1825, 1Q/1Y=7300).
        macro-timeline 엔드포인트는 lookback_days 없이 period(1M/3M/.../10Y)
        의 lookback 시맨틱을 그대로 유지.
        """
        async def _notify(step: str, label: str, pct: int) -> None:
            if on_progress is None:
                return
            try:
                await on_progress(step, label, pct)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CollectMacro] on_progress 콜백 예외: %s", exc)

        settings = get_settings()
        effective_top_n = top_n if top_n is not None else settings.macro_timeline_top_n

        if lookback_days is not None:
            start_date = date.today() - timedelta(days=lookback_days)
        else:
            start_date = _period_to_start_date(period)
        end_date = date.today()

        fred_region = region if region in {"US", "KR"} else "US"

        await _notify("collect", "데이터 소스 병렬 수집 중...", 15)

        fred_task = GetEconomicEventsUseCase(fred_macro_port=self._fred).execute(
            period=period if period.upper() in {"1D", "1W", "1M", "1Y"} else "1Y",
            region=fred_region,
            surprise_only=True,
        )
        # curated 카탈로그는 period와 무관하게 전체를 가져와 LLM 랭커에 정렬을 위임한다.
        # 기간 필터를 걸면 리먼(2008)/COVID(2020) 등 역사 이벤트가 1Y 응답에서 영구 제외된다.
        curated_task = self._curated.fetch(region=region)
        related_task = (
            self._related.fetch_significant_moves(
                start_date=start_date,
                end_date=end_date,
                threshold_pct=settings.history_related_assets_threshold_pct,
                top_k=settings.history_related_assets_top_k,
            )
            if self._related is not None
            else asyncio.sleep(0, result=[])
        )
        gpr_task = (
            self._gpr.fetch_mom_spikes(
                start_date=start_date,
                end_date=end_date,
                mom_change_pct=settings.history_gpr_mom_change_pct,
                top_k=settings.history_gpr_top_k,
            )
            if self._gpr is not None
            else asyncio.sleep(0, result=[])
        )

        fred_result, curated_result, related_result, gpr_result = await asyncio.gather(
            fred_task, curated_task, related_task, gpr_task,
            return_exceptions=True,
        )

        timeline: List[TimelineEvent] = []

        if isinstance(curated_result, list):
            timeline.extend(_from_curated(e) for e in curated_result)
            logger.info(
                "[CollectMacro]   curated: %d건 (region=%s)",
                len(curated_result), region,
            )
        else:
            logger.warning("[CollectMacro]   curated 실패: %s", curated_result)

        if isinstance(fred_result, EconomicEventsResponse):
            fred_events = _from_fred_response(fred_result)
            # §13.4 B perf: 20년 윈도우 fetch 시 FRED surprise 도 폭증 — 최신순 cap
            fred_cap = settings.history_fred_surprise_top_k
            if len(fred_events) > fred_cap:
                fred_events = sorted(fred_events, key=lambda e: e.date, reverse=True)[:fred_cap]
            timeline.extend(fred_events)
            logger.info("[CollectMacro]   FRED surprise: %d건", len(fred_events))
        else:
            logger.warning("[CollectMacro]   FRED 실패: %s", fred_result)

        if isinstance(related_result, list):
            ctx_events = _from_macro_context(related_result)
            timeline.extend(ctx_events)
            logger.info("[CollectMacro]   related_assets: %d건", len(ctx_events))
        else:
            logger.warning("[CollectMacro]   related_assets 실패: %s", related_result)

        if isinstance(gpr_result, list):
            gpr_events = _from_macro_context(gpr_result)
            timeline.extend(gpr_events)
            logger.info("[CollectMacro]   GPR: %d건", len(gpr_events))
        else:
            logger.warning("[CollectMacro]   GPR 실패: %s", gpr_result)

        pool_size = len(timeline)
        timeline = _dedupe(timeline)
        logger.info(
            "[CollectMacro] dedupe: %d → %d (region=%s, period=%s)",
            pool_size, len(timeline), region, period,
        )
        await _notify("rank", "LLM 중요도 랭킹 중...", 60)

        if settings.macro_importance_llm_enabled:
            try:
                await self._ranker.score(timeline)
            except Exception as exc:  # noqa: BLE001
                # 랭커 실패(DB 스키마 이슈 포함) 시에도 타임라인 자체는 돌려준다.
                # 세션 aborted 상태는 호출부(HistoryAgentUseCase)에서 rollback 처리.
                logger.warning(
                    "[CollectMacro] ranker.score 실패 — 중립값(0.5)로 대체: error_type=%s error=%s",
                    type(exc).__name__, exc,
                )
                for e in timeline:
                    if e.importance_score is None:
                        e.importance_score = 0.5
                # 세션 aborted 상태에서 벗어나 이후 쿼리(새 요청)가 가능하도록 롤백.
                await self._enrichment_repo.rollback()
        else:
            for e in timeline:
                if e.importance_score is None:
                    e.importance_score = 0.5

        timeline.sort(
            key=lambda e: (
                -(e.importance_score or 0.0),
                -e.date.toordinal(),
            )
        )

        result = timeline[:effective_top_n]
        await _notify("finalize", "응답 생성 중...", 95)
        logger.info(
            "[CollectMacro] 완료: pool=%d → top_n=%d (region=%s, period=%s)",
            len(timeline), len(result), region, period,
        )
        return result
