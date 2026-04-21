from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from app.domains.agent.application.response.investment_signal_response import (
    InvestmentSignal,
    InvestmentSignalResponse,
)
from app.domains.agent.domain.value_object.source_tier import SourceTier


class AgentStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    NO_DATA = "no_data"


class SubAgentResponse(BaseModel):
    agent_name: str
    status: AgentStatus
    data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_ms: int
    signal: Optional[InvestmentSignal] = None
    confidence: Optional[float] = None
    summary: Optional[str] = None
    key_points: Optional[list[str]] = None
    source_tier: Optional[SourceTier] = None

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        allowed = {"stock", "news", "finance", "disclosure"}
        if v not in allowed:
            raise ValueError(
                f"허용되지 않는 에이전트입니다: {v}. "
                f"허용 목록: {', '.join(sorted(allowed))}"
            )
        return v

    @field_validator("execution_time_ms")
    @classmethod
    def validate_execution_time(cls, v: int) -> int:
        if v < 0:
            raise ValueError("execution_time_ms는 0 이상이어야 합니다")
        return v

    def is_success(self) -> bool:
        return self.status == AgentStatus.SUCCESS

    def is_error(self) -> bool:
        return self.status == AgentStatus.ERROR

    def get_investment_signal(self) -> Optional[InvestmentSignalResponse]:
        if self.signal is None:
            return None

        return InvestmentSignalResponse(
            agent_name=self.agent_name,
            ticker=self.data.get("ticker", "") if self.data else "",
            signal=self.signal,
            confidence=self.confidence,
            summary=self.summary,
            key_points=self.key_points or [],
        )

    @classmethod
    def success(
        cls, agent_name: str, data: dict[str, Any], execution_time_ms: int
    ) -> "SubAgentResponse":
        return cls(
            agent_name=agent_name,
            status=AgentStatus.SUCCESS,
            data=data,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def success_with_signal(
        cls,
        signal: InvestmentSignalResponse,
        data: dict[str, Any],
        execution_time_ms: int,
    ) -> "SubAgentResponse":
        return cls(
            agent_name=signal.agent_name,
            status=AgentStatus.SUCCESS,
            data=data,
            execution_time_ms=execution_time_ms,
            signal=signal.signal,
            confidence=signal.confidence,
            summary=signal.summary,
            key_points=signal.key_points,
        )

    @classmethod
    def error(
        cls, agent_name: str, error_message: str, execution_time_ms: int
    ) -> "SubAgentResponse":
        return cls(
            agent_name=agent_name,
            status=AgentStatus.ERROR,
            data=None,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def no_data(
        cls, agent_name: str, execution_time_ms: int
    ) -> "SubAgentResponse":
        return cls(
            agent_name=agent_name,
            status=AgentStatus.NO_DATA,
            data=None,
            execution_time_ms=execution_time_ms,
        )
