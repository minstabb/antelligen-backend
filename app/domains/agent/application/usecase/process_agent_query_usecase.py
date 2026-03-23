import uuid

from app.domains.agent.application.port.sub_agent_provider import SubAgentProvider
from app.domains.agent.application.request.agent_query_request import AgentQueryRequest
from app.domains.agent.application.response.agent_query_response import (
    AgentQueryResponse,
    QueryResultStatus,
)
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.agent.domain.entity.agent_query import AgentQuery, QueryOptions, UserProfile

DEFAULT_AGENTS = ["stock", "news", "finance", "disclosure"]

SIGNAL_LABEL = {
    "bullish": "매수",
    "bearish": "매도",
    "neutral": "중립",
}


class ProcessAgentQueryUseCase:
    def __init__(self, provider: SubAgentProvider):
        self.provider = provider

    def execute(self, request: AgentQueryRequest) -> AgentQueryResponse:
        options = None
        if request.options:
            options = QueryOptions(
                agents=request.options.agents,
                max_tokens=request.options.max_tokens,
            )

        user_profile = None
        if request.user_profile:
            user_profile = UserProfile(
                risk_level=request.user_profile.risk_level.value,
                investment_horizon=request.user_profile.investment_horizon.value,
            )

        query = AgentQuery(
            query=request.query,
            ticker=request.ticker,
            session_id=request.session_id or str(uuid.uuid4()),
            user_profile=user_profile,
            options=options,
        )

        agents_to_call = query.requested_agents() or DEFAULT_AGENTS
        agent_results: list[SubAgentResponse] = []

        for agent_name in agents_to_call:
            result = self.provider.call(agent_name, query.ticker, query.query)
            agent_results.append(result)

        result_status = AgentQueryResponse.determine_status(agent_results)
        total_time = sum(r.execution_time_ms for r in agent_results)
        answer = self._build_answer(query, agent_results, result_status)

        return AgentQueryResponse(
            session_id=query.session_id,
            result_status=result_status,
            answer=answer,
            agent_results=agent_results,
            total_execution_time_ms=total_time,
        )

    def _build_answer(
        self,
        query: AgentQuery,
        results: list[SubAgentResponse],
        status: QueryResultStatus,
    ) -> str:
        if status == QueryResultStatus.FAILURE:
            return "U요청하신 정보를 조회할 수 없습니다. 잠시 후 다시 시도해 주세요."

        failed_names = [r.agent_name for r in results if r.is_error()]
        parts = []

        for result in results:
            if not result.is_success() or result.data is None:
                continue

            signal = result.get_investment_signal()

            if result.agent_name == "stock":
                parts.append(
                    f"{result.data.get('stock_name', '')}({result.data.get('ticker', '')}) "
                    f"현재가  {result.data.get('현재가 ', 0):,} "
                    f"변동률  {result.data.get('변동률 ', 0)}%"
                )
            elif signal:
                label = SIGNAL_LABEL.get(signal.signal.value, signal.signal.value)
                parts.append(
                    f"[{result.agent_name}] {signal.summary} "
                    f"(시그널: {label}, 신뢰도: {signal.confidence:.0%})"
                )

        answer = ". ".join(parts) + "." if parts else "조회 결과가 없습니다."

        if status == QueryResultStatus.PARTIAL_FAILURE and failed_names:
            answer += f" (일부 조회 실패: {', '.join(failed_names)})"

        return answer
