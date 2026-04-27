from enum import Enum
from typing import Optional

from pydantic import BaseModel

from app.domains.agent.application.response.agent_business_overview import (
    AgentBusinessOverview,
)
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse


class QueryResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILURE = "failure"


class AgentQueryResponse(BaseModel):
    session_id: str
    result_status: QueryResultStatus
    answer: str
    agent_results: list[SubAgentResponse]
    total_execution_time_ms: int
    business_overview: Optional[AgentBusinessOverview] = None

    def has_failures(self) -> bool:
        return any(r.is_error() for r in self.agent_results)

    def successful_agents(self) -> list[str]:
        return [r.agent_name for r in self.agent_results if r.is_success()]

    def failed_agents(self) -> list[str]:
        return [r.agent_name for r in self.agent_results if r.is_error()]

    @classmethod
    def determine_status(
        cls, agent_results: list[SubAgentResponse]
    ) -> QueryResultStatus:
        if not agent_results:
            return QueryResultStatus.FAILURE

        success_count = sum(1 for r in agent_results if r.is_success())

        if success_count == len(agent_results):
            return QueryResultStatus.SUCCESS
        elif success_count > 0:
            return QueryResultStatus.PARTIAL_FAILURE
        else:
            return QueryResultStatus.FAILURE
