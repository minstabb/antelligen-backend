from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from app.domains.agent.application.request.agent_query_request import (
    UserProfileRequest,
)


class FinanceAnalysisRequest(BaseModel):
    ticker: Optional[str] = None
    company_name: Optional[str] = None
    query: str
    session_id: Optional[str] = None
    user_profile: Optional[UserProfileRequest] = None

    @field_validator("ticker", "company_name")
    @classmethod
    def normalize_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None

        value = v.strip()
        return value or None

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value

    @model_validator(mode="after")
    def validate_identifier(self) -> "FinanceAnalysisRequest":
        if not self.ticker and not self.company_name:
            raise ValueError("ticker or company_name must be provided")
        return self
