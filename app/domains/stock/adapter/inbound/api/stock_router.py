from fastapi import APIRouter

from app.common.exception.app_exception import AppException
from app.common.response.base_response import BaseResponse
from app.domains.stock.adapter.outbound.external.opendart_financial_data_provider import (
    OpenDartFinancialDataProvider,
)
from app.domains.stock.adapter.outbound.external.serp_stock_data_collector import (
    SerpStockDataCollector,
)
from app.domains.stock.adapter.outbound.persistence.corp_code_repository_impl import (
    CorpCodeRepositoryImpl,
)
from app.domains.stock.adapter.outbound.persistence.stock_repository_impl import (
    StockRepositoryImpl,
)
from app.domains.stock.adapter.outbound.persistence.stock_vector_repository_impl import (
    StockVectorRepositoryImpl,
)
from app.domains.stock.application.response.stock_collection_response import (
    StockCollectionResponse,
)
from app.domains.stock.application.response.stock_response import StockResponse
from app.domains.stock.application.usecase.collect_stock_data_usecase import (
    CollectStockDataUseCase,
)
from app.domains.stock.application.usecase.fetch_dart_financial_ratios_usecase import (
    FetchDartFinancialRatiosUseCase,
)
from app.domains.stock.infrastructure.mapper.serp_stock_data_standardizer import (
    SerpStockDataStandardizer,
)
from app.domains.stock.infrastructure.mapper.deterministic_stock_embedding_generator import (
    DeterministicStockEmbeddingGenerator,
)
from app.domains.stock.infrastructure.mapper.simple_stock_document_chunker import (
    SimpleStockDocumentChunker,
)
from app.domains.stock.application.usecase.get_stock_usecase import GetStockUseCase
from app.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/stock", tags=["Stock"])


@router.get("/{ticker}", response_model=StockResponse)
async def get_stock(ticker: str):
    repository = StockRepositoryImpl()
    usecase = GetStockUseCase(repository)
    result = await usecase.execute(ticker)
    if result is None:
        raise AppException(status_code=404, message=f"종목을 찾을 수 없습니다: {ticker}")
    return result


@router.get("/{ticker}/collect", response_model=BaseResponse[StockCollectionResponse])
async def collect_stock_data(ticker: str):
    """
    외부 API(SerpAPI + DART)에서 데이터를 수집하여 벡터 DB에 저장합니다.
    """
    settings = get_settings()
    repository = StockRepositoryImpl()
    vector_repository = StockVectorRepositoryImpl()

    # DART 재무비율 UseCase (선택적)
    dart_financial_ratios_usecase = None
    if settings.dart_api_key:
        dart_financial_ratios_usecase = FetchDartFinancialRatiosUseCase(
            corp_code_repository=CorpCodeRepositoryImpl(),
            dart_financial_data_provider=OpenDartFinancialDataProvider(
                api_key=settings.dart_api_key
            ),
        )

    usecase = CollectStockDataUseCase(
        stock_repository=repository,
        stock_data_collector=SerpStockDataCollector(api_key=settings.serp_api_key),
        stock_data_standardizer=SerpStockDataStandardizer(),
        stock_document_chunker=SimpleStockDocumentChunker(),
        stock_embedding_generator=DeterministicStockEmbeddingGenerator(),
        stock_vector_repository=vector_repository,
        dart_financial_ratios_usecase=dart_financial_ratios_usecase,
    )
    result = await usecase.execute(ticker)
    return BaseResponse.ok(data=result)
