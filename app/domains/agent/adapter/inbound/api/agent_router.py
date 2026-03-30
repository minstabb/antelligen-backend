from fastapi import APIRouter

from app.common.response.base_response import BaseResponse
from app.domains.agent.adapter.outbound.external.mock_sub_agent_provider import (
    MockSubAgentProvider,
)
from app.domains.agent.adapter.outbound.external.openai_finance_agent_provider import (
    OpenAIFinanceAgentProvider,
)
from app.domains.agent.application.request.agent_query_request import AgentQueryRequest
from app.domains.agent.application.request.finance_analysis_request import (
    FinanceAnalysisRequest,
)
from app.domains.agent.application.response.frontend_agent_response import (
    FrontendAgentResponse,
)
from app.domains.agent.application.usecase.analyze_finance_agent_usecase import (
    AnalyzeFinanceAgentUseCase,
)
from app.domains.agent.application.usecase.process_agent_query_usecase import (
    ProcessAgentQueryUseCase,
)
from app.domains.stock.adapter.outbound.persistence.stock_repository_impl import (
    StockRepositoryImpl,
)
from app.domains.stock.adapter.outbound.persistence.stock_vector_repository_impl import (
    StockVectorRepositoryImpl,
)
from app.domains.stock.application.usecase.get_stored_stock_data_usecase import (
    GetStoredStockDataUseCase,
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
):
    """
    벡터 DB에 저장된 데이터를 기반으로 재무 분석을 수행합니다.
    먼저 /stock/{ticker}/collect로 데이터를 적재해야 합니다.
    """
    settings = get_settings()
    stock_repository = StockRepositoryImpl()
    stock_vector_repository = StockVectorRepositoryImpl()

    # 저장된 데이터 조회 UseCase
    get_stored_stock_data_usecase = GetStoredStockDataUseCase(
        stock_repository=stock_repository,
        stock_vector_repository=stock_vector_repository,
    )

    finance_provider = OpenAIFinanceAgentProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_finance_agent_model,
    )

    usecase = AnalyzeFinanceAgentUseCase(
        stock_repository=stock_repository,
        get_stored_stock_data_usecase=get_stored_stock_data_usecase,
        finance_agent_provider=finance_provider,
    )
    internal_result = await usecase.execute(request)
    frontend_result = FrontendAgentResponse.from_internal(internal_result)
    return BaseResponse.ok(data=frontend_result)
