from fastapi import APIRouter, Header

from app.common.response.base_response import BaseResponse
from app.domains.agent.adapter.outbound.external.http_analysis_request_client import (
    HttpAnalysisRequestClient,
)
from app.domains.agent.adapter.outbound.external.mock_sub_agent_provider import (
    MockSubAgentProvider,
)
from app.domains.agent.application.request.agent_query_request import AgentQueryRequest
from app.domains.agent.application.request.finance_analysis_request import (
    FinanceAnalysisRequest,
)
from app.domains.agent.application.response.frontend_agent_response import (
    FrontendAgentResponse,
)
from app.domains.agent.application.usecase.request_finance_analysis_usecase import (
    RequestFinanceAnalysisUseCase,
)
from app.domains.agent.application.usecase.process_agent_query_usecase import (
    ProcessAgentQueryUseCase,
)
from app.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post(
    "/query",
    response_model=BaseResponse[FrontendAgentResponse],
    status_code=200,
)
async def query_agent(request: AgentQueryRequest):
    provider = MockSubAgentProvider()
    usecase = ProcessAgentQueryUseCase(provider)
    internal_result = usecase.execute(request)
    frontend_result = FrontendAgentResponse.from_internal(internal_result)
    return BaseResponse.ok(data=frontend_result)


@router.post(
    "/finance-analysis",
    response_model=BaseResponse[FrontendAgentResponse],
    status_code=200,
)
async def analyze_finance(
    request: FinanceAnalysisRequest,
    authorization: str | None = Header(default=None),
):
    settings = get_settings()
    client = HttpAnalysisRequestClient(
        finance_analysis_url=settings.analysis_api_finance_url,
        timeout_seconds=settings.analysis_api_timeout_seconds,
    )
    usecase = RequestFinanceAnalysisUseCase(client)
    result = await usecase.execute(request=request, authorization=authorization)
    return BaseResponse.ok(data=result)
