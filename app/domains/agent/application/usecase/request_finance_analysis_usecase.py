from app.domains.agent.application.port.analysis_request_client import (
    AnalysisRequestClient,
)
from app.domains.agent.application.request.finance_analysis_request import (
    FinanceAnalysisRequest,
)
from app.domains.agent.application.response.frontend_agent_response import (
    FrontendAgentResponse,
)


class RequestFinanceAnalysisUseCase:
    def __init__(self, analysis_request_client: AnalysisRequestClient):
        self._analysis_request_client = analysis_request_client

    async def execute(
        self,
        request: FinanceAnalysisRequest,
        authorization: str | None = None,
    ) -> FrontendAgentResponse:
        return await self._analysis_request_client.request_finance_analysis(
            request=request,
            authorization=authorization,
        )
