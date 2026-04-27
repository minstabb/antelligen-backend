from abc import ABC, abstractmethod
from typing import Optional

from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.company_profile.domain.value_object.business_overview import (
    BusinessOverview,
)


class LlmSynthesisPort(ABC):
    @abstractmethod
    async def synthesize(
        self,
        ticker: str,
        query: str,
        sub_results: list[SubAgentResponse],
        business_overview: Optional[BusinessOverview] = None,
        corp_name: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """서브에이전트 결과를 종합하여 (summary, key_points) 반환.

        business_overview 가 주어지면 회사의 사업 모델·매출원 컨텍스트를 함께 활용해
        더 풍부한 종합 의견을 생성한다.
        """
        pass
