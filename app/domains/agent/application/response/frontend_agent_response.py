from typing import Any, Optional

from pydantic import BaseModel

from app.domains.agent.application.response.agent_business_overview import (
    AgentBusinessOverview,
)
from app.domains.agent.application.response.agent_query_response import (
    AgentQueryResponse,
    QueryResultStatus,
)


class FrontendAgentResultItem(BaseModel):
    agent_name: str
    status: str
    data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_ms: int
    signal: Optional[str] = None
    confidence: Optional[float] = None
    summary: Optional[str] = None
    key_points: Optional[list[str]] = None


class FrontendAgentResponse(BaseModel):
    session_id: str
    result_status: QueryResultStatus
    answer: str
    agent_results: list[FrontendAgentResultItem]
    total_execution_time_ms: int
    business_overview: Optional[AgentBusinessOverview] = None

    @classmethod
    def from_internal(cls, response: AgentQueryResponse) -> "FrontendAgentResponse":
        agent_results = [
            FrontendAgentResultItem(
                agent_name=r.agent_name,
                status=r.status.value,
                data={k: v for k, v in r.data.items() if k != "retrieved_chunks"} if r.data else None,
                error_message=r.error_message,
                execution_time_ms=r.execution_time_ms,
                signal=r.signal.value if r.signal else None,
                confidence=r.confidence,
                summary=r.summary,
                key_points=r.key_points,
            )
            for r in response.agent_results
        ]

        return cls(
            session_id=response.session_id,
            result_status=response.result_status,
            answer=response.answer,
            agent_results=agent_results,
            total_execution_time_ms=response.total_execution_time_ms,
            business_overview=response.business_overview,
        )
