import asyncio
import time
import uuid
from typing import Optional

from app.domains.agent.application.port.disclosure_agent_port import DisclosureAgentPort
from app.domains.agent.application.port.finance_agent_port import FinanceAgentPort
from app.domains.agent.application.port.integrated_analysis_repository_port import (
    IntegratedAnalysisRepositoryPort,
)
from app.domains.agent.application.port.llm_synthesis_port import LlmSynthesisPort
from app.domains.agent.application.port.news_agent_port import NewsAgentPort
from app.domains.agent.application.request.agent_query_request import AgentQueryRequest
from app.domains.agent.application.response.agent_query_response import (
    AgentQueryResponse,
    QueryResultStatus,
)
from app.domains.agent.application.response.integrated_analysis_response import (
    IntegratedAnalysisResponse,
)
from app.domains.agent.application.response.investment_signal_response import InvestmentSignal
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.agent.domain.value_object.source_tier import SourceTier, default_multiplier
from app.infrastructure.config.settings import get_settings

DEFAULT_TICKER = "005930"

_SIGNAL_SCORE = {
    InvestmentSignal.BULLISH: 1.0,
    InvestmentSignal.NEUTRAL: 0.0,
    InvestmentSignal.BEARISH: -1.0,
}


class ProcessAgentQueryUseCase:
    def __init__(
        self,
        news_agent: NewsAgentPort,
        disclosure_agent: DisclosureAgentPort,
        finance_agent: FinanceAgentPort,
        llm_synthesis: LlmSynthesisPort,
        repository: Optional[IntegratedAnalysisRepositoryPort] = None,
    ) -> None:
        self._news = news_agent
        self._disclosure = disclosure_agent
        self._finance = finance_agent
        self._llm_synthesis = llm_synthesis
        self._repository = repository

    async def execute(self, request: AgentQueryRequest) -> AgentQueryResponse:
        start = time.monotonic()
        ticker = request.ticker or DEFAULT_TICKER
        session_id = request.session_id or str(uuid.uuid4())

        # 1. PostgreSQL 캐시 확인 (1시간 이내 결과 재사용)
        if self._repository:
            cached = await self._repository.find_recent(ticker, within_seconds=3600)
            if cached:
                return self._from_cached(cached, session_id)

        # 2. 3개 서브에이전트 병렬 호출 (하나 실패해도 계속)
        news_r, disclosure_r, finance_r = await asyncio.gather(
            self._news.analyze(ticker, request.query),
            self._disclosure.analyze(ticker),
            self._finance.analyze(ticker, request.query),
            return_exceptions=True,
        )

        agent_results = [
            self._coerce(news_r, "news"),
            self._coerce(disclosure_r, "disclosure"),
            self._coerce(finance_r, "finance"),
        ]

        # 3. 시그널 가중 집계
        overall_signal, overall_confidence = self._aggregate_signals(agent_results)

        # 4. LLM 종합 요약 생성
        summary, key_points = await self._llm_synthesis.synthesize(
            ticker=ticker,
            query=request.query,
            sub_results=agent_results,
        )

        elapsed = int((time.monotonic() - start) * 1000)

        # 5. PostgreSQL에 저장 (전체 성공일 때만 캐시)
        result_status = AgentQueryResponse.determine_status(agent_results)
        if self._repository and result_status == QueryResultStatus.SUCCESS:
            integrated = IntegratedAnalysisResponse(
                ticker=ticker,
                query=request.query,
                overall_signal=overall_signal,
                confidence=overall_confidence,
                summary=summary,
                key_points=key_points,
                sub_results=[r.model_dump(mode="json") for r in agent_results],
                execution_time_ms=elapsed,
            )
            await self._repository.save(integrated)

        return AgentQueryResponse(
            session_id=session_id,
            result_status=result_status,
            answer=summary,
            agent_results=agent_results,
            total_execution_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce(result: object, agent_name: str) -> SubAgentResponse:
        if isinstance(result, SubAgentResponse):
            return result
        msg = str(result) if isinstance(result, Exception) else "알 수 없는 오류"
        return SubAgentResponse.error(agent_name, msg, 0)

    @staticmethod
    def _aggregate_signals(results: list[SubAgentResponse]) -> tuple[str, float]:
        settings = get_settings()
        use_tier = settings.enable_source_tier_weighting

        _AGENT_DEFAULT_TIER = {
            "news": SourceTier.MEDIUM,
            "disclosure": SourceTier.HIGH,
            "finance": SourceTier.HIGH,
        }

        weighted_score = 0.0
        confidence_total = 0.0
        count = 0

        for r in results:
            if r.is_success() and r.signal is not None and r.confidence is not None:
                score = _SIGNAL_SCORE.get(r.signal, 0.0)
                confidence = r.confidence
                if use_tier:
                    tier = r.source_tier or _AGENT_DEFAULT_TIER.get(r.agent_name, SourceTier.MEDIUM)
                    multiplier = default_multiplier(tier)
                    confidence = confidence * multiplier
                weighted_score += score * confidence
                confidence_total += confidence
                count += 1

        if count == 0:
            return "neutral", 0.0

        avg_confidence = confidence_total / count
        avg_score = weighted_score / confidence_total if confidence_total > 0 else 0.0

        if avg_score > 0.2:
            signal = "bullish"
        elif avg_score < -0.2:
            signal = "bearish"
        else:
            signal = "neutral"

        return signal, round(avg_confidence, 4)

    @staticmethod
    def _from_cached(cached: IntegratedAnalysisResponse, session_id: str) -> AgentQueryResponse:
        agent_results = []
        for item in cached.sub_results:
            try:
                agent_results.append(SubAgentResponse.model_validate(item))
            except Exception:
                pass
        return AgentQueryResponse(
            session_id=session_id,
            result_status=AgentQueryResponse.determine_status(agent_results),
            answer=cached.summary,
            agent_results=agent_results,
            total_execution_time_ms=cached.execution_time_ms,
        )
