from typing import Optional

from pydantic import BaseModel, Field

from app.domains.company_profile.domain.value_object.business_overview import (
    BusinessOverview,
)


class AgentBusinessOverview(BaseModel):
    """통합 에이전트 응답에 포함되는 회사 비즈니스 요약.

    company_profile 도메인의 `BusinessOverview` VO 를 그대로 직렬화하면서
    프런트엔드 표시용으로 회사 표시명(`corp_name`) 을 함께 노출한다.
    """

    corp_name: str
    summary: str
    revenue_sources: list[str] = Field(default_factory=list)
    source: str  # "rag_summary" | "llm_only" | "asset_llm_only"
    founding_story: Optional[str] = None
    business_model: Optional[str] = None

    @classmethod
    def from_overview(
        cls, corp_name: str, overview: BusinessOverview
    ) -> "AgentBusinessOverview":
        return cls(
            corp_name=corp_name,
            summary=overview.summary,
            revenue_sources=list(overview.revenue_sources),
            source=overview.source,
            founding_story=overview.founding_story,
            business_model=overview.business_model,
        )
