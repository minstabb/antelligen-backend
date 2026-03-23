from fastapi import APIRouter

from app.common.exception.app_exception import AppException
from app.common.response.base_response import BaseResponse
from app.domains.stock.adapter.outbound.external.serp_stock_data_collector import (
    SerpStockDataCollector,
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
    settings = get_settings()
    repository = StockRepositoryImpl()
    collector = SerpStockDataCollector(api_key=settings.serp_api_key)
    standardizer = SerpStockDataStandardizer()
    chunker = SimpleStockDocumentChunker()
    embedding_generator = DeterministicStockEmbeddingGenerator()
    vector_repository = StockVectorRepositoryImpl()
    usecase = CollectStockDataUseCase(
        stock_repository=repository,
        stock_data_collector=collector,
        stock_data_standardizer=standardizer,
        stock_document_chunker=chunker,
        stock_embedding_generator=embedding_generator,
        stock_vector_repository=vector_repository,
    )
    result = await usecase.execute(ticker)
    return BaseResponse.ok(data=result)
