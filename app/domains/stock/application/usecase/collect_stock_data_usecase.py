import logging

from app.common.exception.app_exception import AppException
from app.domains.stock.application.port.stock_data_collector import StockDataCollector
from app.domains.stock.application.port.stock_document_chunker import (
    StockDocumentChunker,
)
from app.domains.stock.application.port.stock_embedding_generator import (
    StockEmbeddingGenerator,
)
from app.domains.stock.application.port.stock_repository import StockRepository
from app.domains.stock.application.port.stock_vector_repository import (
    StockVectorRepository,
)
from app.domains.stock.application.port.stock_data_standardizer import (
    StockDataStandardizer,
)
from app.domains.stock.application.response.stock_collection_response import (
    StockBasicInformationResponse,
    StockCollectionResponse,
    StockDartFinancialRatioResponse,
    StockDocumentChunkResponse,
    StockIngestionReadyDataResponse,
    StockCollectionMetadataResponse,
    StockFinancialInformationResponse,
    StockVectorStoreResultResponse,
)
from app.domains.stock.application.usecase.fetch_dart_financial_ratios_usecase import (
    FetchDartFinancialRatiosUseCase,
)
from app.domains.stock.domain.entity.stock_vector_document import StockVectorDocument

logger = logging.getLogger(__name__)


class CollectStockDataUseCase:
    def __init__(
        self,
        stock_repository: StockRepository,
        stock_data_collector: StockDataCollector,
        stock_data_standardizer: StockDataStandardizer,
        stock_document_chunker: StockDocumentChunker,
        stock_embedding_generator: StockEmbeddingGenerator,
        stock_vector_repository: StockVectorRepository,
        dart_financial_ratios_usecase: FetchDartFinancialRatiosUseCase | None = None,
    ):
        self._stock_repository = stock_repository
        self._stock_data_collector = stock_data_collector
        self._stock_data_standardizer = stock_data_standardizer
        self._stock_document_chunker = stock_document_chunker
        self._stock_embedding_generator = stock_embedding_generator
        self._stock_vector_repository = stock_vector_repository
        self._dart_financial_ratios_usecase = dart_financial_ratios_usecase

    async def execute(self, ticker: str) -> StockCollectionResponse:
        stock = await self._stock_repository.find_by_ticker(ticker)
        if stock is None:
            logger.warning("[Stock Collect] Stock not found - ticker=%s", ticker)
            raise AppException(status_code=404, message=f"Stock not found: {ticker}")

        raw_data = await self._stock_data_collector.collect(
            ticker=stock.ticker,
            stock_name=stock.stock_name,
            market=stock.market,
        )
        if raw_data is None:
            logger.warning(
                "[Stock Collect] Raw collection failed - ticker=%s stock_name=%s",
                stock.ticker,
                stock.stock_name,
            )
            raise AppException(
                status_code=404,
                message=f"Unable to collect stock data from external source: {ticker}",
            )

        # DART 재무비율 조회 (표준화 전에 수행하여 document_text에 포함)
        dart_roe = None
        dart_roa = None
        dart_debt_ratio = None
        dart_fiscal_year = None
        if self._dart_financial_ratios_usecase:
            try:
                dart_result = await self._dart_financial_ratios_usecase.execute(
                    ticker=stock.ticker
                )
                if dart_result:
                    dart_roe = dart_result.roe
                    dart_roa = dart_result.roa
                    dart_debt_ratio = dart_result.debt_ratio
                    dart_fiscal_year = dart_result.fiscal_year
                    logger.info(
                        "[Stock Collect] DART 재무비율 조회 성공 - ticker=%s roe=%s roa=%s debt_ratio=%s",
                        stock.ticker,
                        dart_roe,
                        dart_roa,
                        dart_debt_ratio,
                    )
            except Exception as e:
                logger.warning(
                    "[Stock Collect] DART 재무비율 조회 실패 - ticker=%s error=%s",
                    stock.ticker,
                    str(e),
                )

        collected_data = self._stock_data_standardizer.standardize(
            raw_data,
            dart_roe=dart_roe,
            dart_roa=dart_roa,
            dart_debt_ratio=dart_debt_ratio,
            dart_fiscal_year=dart_fiscal_year,
        )
        if collected_data is None:
            logger.error(
                "[Stock Collect] Standardization failed - ticker=%s source=%s",
                stock.ticker,
                raw_data.source,
            )
            raise AppException(
                status_code=500,
                message=f"Unable to transform raw stock data into internal standard structure: {ticker}",
            )

        if not collected_data.collected_types:
            logger.error(
                "[Stock Collect] No supported collection types - ticker=%s source=%s",
                collected_data.ticker,
                collected_data.source,
            )
            raise AppException(
                status_code=500,
                message=f"No supported collection types were produced: {ticker}",
            )

        basic_information = None
        if "basic_information" in collected_data.collected_types:
            basic_information = StockBasicInformationResponse(
                ticker=collected_data.ticker,
                stock_name=collected_data.stock_name,
                market=collected_data.market,
                company_summary=collected_data.company_summary,
            )

        financial_information = None
        if "financial_information" in collected_data.collected_types:
            financial_information = StockFinancialInformationResponse(
                current_price=collected_data.current_price,
                currency=collected_data.currency,
                market_cap=collected_data.market_cap,
                pe_ratio=collected_data.pe_ratio,
                dividend_yield=collected_data.dividend_yield,
            )

        document_chunks = []
        vector_store_result = StockVectorStoreResultResponse(
            total_chunk_count=0,
            stored_chunk_count=0,
            skipped_chunk_count=0,
            duplicate_prevented=False,
        )
        if collected_data.document_text:
            chunk_entities = self._stock_document_chunker.chunk(
                entity_id=collected_data.ticker,
                source=collected_data.source,
                dedup_key=collected_data.dedup_key,
                document_text=collected_data.document_text,
            )
            vector_documents: list[StockVectorDocument] = []

            for chunk in chunk_entities:
                chunk.embedding_vector = self._stock_embedding_generator.generate(
                    chunk.content
                )
                vector_documents.append(
                    StockVectorDocument(
                        chunk_id=chunk.chunk_id,
                        entity_id=collected_data.ticker,
                        source=collected_data.source,
                        dedup_key=collected_data.dedup_key,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        embedding_vector=chunk.embedding_vector,
                        collected_at=collected_data.collected_at,
                    )
                )

            stored_result = await self._stock_vector_repository.save_documents(
                vector_documents
            )
            vector_store_result = StockVectorStoreResultResponse(
                total_chunk_count=stored_result.total_chunk_count,
                stored_chunk_count=stored_result.stored_chunk_count,
                skipped_chunk_count=stored_result.skipped_chunk_count,
                duplicate_prevented=stored_result.duplicate_prevented,
            )
            document_chunks = [
                StockDocumentChunkResponse(
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    embedding_vector=chunk.embedding_vector or [],
                )
                for chunk in chunk_entities
            ]

        # DART 재무비율 응답 (이미 조회하여 document_text에 포함됨)
        dart_financial_ratios = None
        if collected_data.dart_roe is not None or collected_data.dart_roa is not None or collected_data.dart_debt_ratio is not None:
            dart_financial_ratios = StockDartFinancialRatioResponse(
                roe=collected_data.dart_roe,
                roa=collected_data.dart_roa,
                debt_ratio=collected_data.dart_debt_ratio,
                fiscal_year=collected_data.dart_fiscal_year,
            )

        return StockCollectionResponse(
            ticker=collected_data.ticker,
            stock_name=collected_data.stock_name,
            market=collected_data.market,
            collected_types=collected_data.collected_types,
            metadata=StockCollectionMetadataResponse(
                entity_id=collected_data.ticker,
                source=collected_data.source,
                collected_at=collected_data.collected_at,
                dedup_key=collected_data.dedup_key,
                dedup_basis=collected_data.dedup_basis,
                reference_url=collected_data.reference_url,
            ),
            ingestion_ready_data=StockIngestionReadyDataResponse(
                entity_id=collected_data.ticker,
                source=collected_data.source,
                collected_at=collected_data.collected_at,
                dedup_key=collected_data.dedup_key,
                collected_types=collected_data.collected_types,
                content=collected_data.document_text or "",
            ),
            basic_information=basic_information,
            financial_information=financial_information,
            dart_financial_ratios=dart_financial_ratios,
            document_text=collected_data.document_text,
            document_chunks=document_chunks,
            vector_store_result=vector_store_result,
        )
