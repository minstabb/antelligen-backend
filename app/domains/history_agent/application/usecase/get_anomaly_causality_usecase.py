import logging
from datetime import date, timedelta
from typing import Optional

from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.application.response.anomaly_causality_response import (
    AnomalyCausalityResponse,
)
from app.domains.history_agent.application.response.timeline_response import HypothesisResult
from app.domains.history_agent.domain.entity.event_enrichment import (
    EventEnrichment,
    compute_detail_hash,
)
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

ANOMALY_EVENT_TYPE = "ANOMALY_BAR"

# §13.4 D — 봉 단위별 causality 분석 윈도우 multiplier.
# 일봉 이상치는 단일 뉴스/공시로 설명 가능 (좁은 윈도우),
# 분기봉 이상치는 거시 trend 로 설명 (넓은 윈도우) — plan §13.4 D 참조.
_CHART_INTERVAL_WINDOW_MULTIPLIER: dict[str, int] = {
    "1D": 1,
    "1W": 7,
    "1M": 30,
    "1Q": 90,
    "1Y": 90,  # legacy alias for 1Q
}
_DEFAULT_WINDOW_MULTIPLIER = 1


class GetAnomalyCausalityUseCase:
    """이상치 봉 1건의 causality(인과 가설)를 조회한다.

    - DB `event_enrichments` 캐시(event_type="ANOMALY_BAR")를 먼저 조회해 히트 시 즉시 반환.
    - 미스 시 `run_causality_agent`를 호출하고 결과를 캐시에 upsert.
    - 캐시·LLM 실패는 빈 hypotheses로 graceful degrade.
    - §13.4 D: chart_interval 별 lookback 윈도우 multiplier 적용. 캐시 키는
      chart_interval 포함해 봉 단위별 causality 가 분리 저장되도록 한다.
    """

    def __init__(self, enrichment_repo: EventEnrichmentRepositoryPort):
        self._enrichment_repo = enrichment_repo

    async def execute(
        self,
        ticker: str,
        bar_date: date,
        chart_interval: Optional[str] = None,
    ) -> AnomalyCausalityResponse:
        # 캐시 키에 chart_interval 포함 — None 이면 빈 문자열 (backward compat)
        ci = (chart_interval or "").upper()
        detail_hash = compute_detail_hash(f"{ticker}|{bar_date.isoformat()}|{ci}")
        key = (ticker, bar_date, ANOMALY_EVENT_TYPE, detail_hash)

        try:
            cached = await self._enrichment_repo.find_by_keys([key])
        except Exception as exc:
            logger.warning(
                "[AnomalyCausality] 캐시 조회 실패: ticker=%s, date=%s, error=%s",
                ticker, bar_date, exc,
            )
            cached = []

        if cached and cached[0].causality is not None:
            logger.info(
                "[AnomalyCausality] 캐시 히트: ticker=%s, date=%s, n=%d",
                ticker, bar_date, len(cached[0].causality),
            )
            return AnomalyCausalityResponse(
                ticker=ticker,
                date=bar_date,
                hypotheses=[HypothesisResult(**h) for h in cached[0].causality],
                cached=True,
            )

        from app.domains.causality_agent.application.causality_agent_workflow import (
            run_causality_agent,
        )

        settings = get_settings()
        multiplier = _CHART_INTERVAL_WINDOW_MULTIPLIER.get(ci, _DEFAULT_WINDOW_MULTIPLIER)
        pre_days = settings.history_causality_pre_days * multiplier
        post_days = settings.history_causality_post_days * multiplier
        start_date = bar_date - timedelta(days=pre_days)
        end_date = bar_date + timedelta(days=post_days)
        if multiplier > 1:
            logger.info(
                "[AnomalyCausality] chart_interval=%s 윈도우 확장: pre=%d post=%d",
                ci, pre_days, post_days,
            )

        try:
            state = await run_causality_agent(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
            )
            hypotheses_raw = state.get("hypotheses", [])
        except Exception as exc:
            logger.warning(
                "[AnomalyCausality] agent 실패: ticker=%s, date=%s, error=%s",
                ticker, bar_date, exc,
            )
            hypotheses_raw = []

        hypotheses = [HypothesisResult(**h) for h in hypotheses_raw]

        try:
            await self._enrichment_repo.upsert_bulk([
                EventEnrichment(
                    ticker=ticker,
                    event_date=bar_date,
                    event_type=ANOMALY_EVENT_TYPE,
                    detail_hash=detail_hash,
                    title="",
                    causality=[h.model_dump() for h in hypotheses],
                )
            ])
            logger.info(
                "[AnomalyCausality] 캐시 저장: ticker=%s, date=%s, n=%d",
                ticker, bar_date, len(hypotheses),
            )
        except Exception as exc:
            logger.warning(
                "[AnomalyCausality] 캐시 저장 실패: ticker=%s, date=%s, error=%s",
                ticker, bar_date, exc,
            )
            await self._enrichment_repo.rollback()

        return AnomalyCausalityResponse(
            ticker=ticker,
            date=bar_date,
            hypotheses=hypotheses,
            cached=False,
        )
