from abc import ABC, abstractmethod

from app.domains.agent.application.request.finance_analysis_request import (
    FinanceAnalysisRequest,
)
from app.domains.agent.application.response.frontend_agent_response import (
    FrontendAgentResponse,
)


class AnalysisRequestClient(ABC):
    @abstractmethod
    async def request_finance_analysis(
        self,
        request: FinanceAnalysisRequest,
        authorization: str | None = None,
    ) -> FrontendAgentResponse:
        pass
