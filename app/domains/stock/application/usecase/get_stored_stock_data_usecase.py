import logging
import re

from app.common.exception.app_exception import AppException
from app.domains.stock.application.port.stock_repository import StockRepository
from app.domains.stock.application.port.stock_vector_repository import (
    StockVectorRepository,
)
from app.domains.stock.application.response.stock_collection_response import (
    StockBasicInformationResponse,
    StockCollectionMetadataResponse,
    StockCollectionResponse,
    StockDartFinancialRatioResponse,
    StockDocumentChunkResponse,
    StockFinancialInformationResponse,
    StockIngestionReadyDataResponse,
    StockVectorStoreResultResponse,
)

logger = logging.getLogger(__name__)


class GetStoredStockDataUseCase:
    """벡터 DB에 저장된 주식 데이터를 조회하는 UseCase"""

    def __init__(
        self,
        stock_repository: StockRepository,
        stock_vector_repository: StockVectorRepository,
    ):
        self._stock_repository = stock_repository
        self._stock_vector_repository = stock_vector_repository

    async def execute(self, ticker: str) -> StockCollectionResponse:
        # 1. 종목 정보 조회
        stock = await self._stock_repository.find_by_ticker(ticker)
        if stock is None:
            raise AppException(status_code=404, message=f"Stock not found: {ticker}")

        # 2. 벡터 DB에서 저장된 문서 조회
        documents = await self._stock_vector_repository.find_by_entity_id(ticker)
        if not documents:
            raise AppException(
                status_code=404,
                message=f"No stored data found for ticker: {ticker}. Please collect data first.",
            )

        # 3. 문서 내용 합치기 (chunk_index 순서대로)
        sorted_docs = sorted(documents, key=lambda d: d.chunk_index)
        full_document_text = "\n".join(doc.content for doc in sorted_docs)

        # 4. document_text에서 정보 파싱
        parsed = self._parse_document_text(full_document_text)

        # 5. 응답 생성
        first_doc = sorted_docs[0]

        basic_information = StockBasicInformationResponse(
            ticker=ticker,
            stock_name=stock.stock_name,
            market=stock.market,
            company_summary=parsed.get("company_summary"),
        )

        financial_information = None
        if any(
            parsed.get(k)
            for k in ["current_price", "market_cap", "pe_ratio", "dividend_yield"]
        ):
            financial_information = StockFinancialInformationResponse(
                current_price=parsed.get("current_price"),
                currency=parsed.get("currency"),
                market_cap=parsed.get("market_cap"),
                pe_ratio=parsed.get("pe_ratio"),
                dividend_yield=parsed.get("dividend_yield"),
            )

        dart_financial_ratios = None
        if any(parsed.get(k) for k in ["dart_roe", "dart_roa", "dart_debt_ratio"]):
            dart_financial_ratios = StockDartFinancialRatioResponse(
                roe=parsed.get("dart_roe"),
                roa=parsed.get("dart_roa"),
                debt_ratio=parsed.get("dart_debt_ratio"),
                fiscal_year=parsed.get("dart_fiscal_year"),
                sales=parsed.get("dart_sales"),
                operating_income=parsed.get("dart_operating_income"),
                net_income=parsed.get("dart_net_income"),
            )

        document_chunks = [
            StockDocumentChunkResponse(
                chunk_id=doc.chunk_id,
                chunk_index=doc.chunk_index,
                content=doc.content,
                start_char=0,
                end_char=len(doc.content),
                embedding_vector=doc.embedding_vector,
            )
            for doc in sorted_docs
        ]

        return StockCollectionResponse(
            ticker=ticker,
            stock_name=stock.stock_name,
            market=stock.market,
            collected_types=["basic_information", "financial_information", "document_text"],
            metadata=StockCollectionMetadataResponse(
                entity_id=first_doc.entity_id,
                source=first_doc.source,
                collected_at=first_doc.collected_at,
                dedup_key=first_doc.dedup_key,
                dedup_basis="stored",
                reference_url=None,
            ),
            ingestion_ready_data=StockIngestionReadyDataResponse(
                entity_id=first_doc.entity_id,
                source=first_doc.source,
                collected_at=first_doc.collected_at,
                dedup_key=first_doc.dedup_key,
                collected_types=["basic_information", "financial_information", "document_text"],
                content=full_document_text,
            ),
            basic_information=basic_information,
            financial_information=financial_information,
            dart_financial_ratios=dart_financial_ratios,
            document_text=full_document_text,
            document_chunks=document_chunks,
            vector_store_result=StockVectorStoreResultResponse(
                total_chunk_count=len(sorted_docs),
                stored_chunk_count=len(sorted_docs),
                skipped_chunk_count=0,
                duplicate_prevented=False,
            ),
        )

    def _parse_document_text(self, text: str) -> dict:
        """document_text에서 정보를 파싱합니다."""
        result: dict = {}

        # Company summary
        match = re.search(r"Company summary:\s*(.+?)(?:\n|$)", text)
        if match:
            result["company_summary"] = match.group(1).strip()

        # Current price (with currency)
        match = re.search(r"Current price:\s*([0-9,\.]+)\s*(\w+)?", text)
        if match:
            result["current_price"] = match.group(1).strip()
            if match.group(2):
                result["currency"] = match.group(2).strip()

        # Market cap
        match = re.search(r"Market cap:\s*(.+?)(?:\n|$)", text)
        if match:
            result["market_cap"] = match.group(1).strip()

        # PER
        match = re.search(r"PER:\s*(.+?)(?:\n|$)", text)
        if match:
            result["pe_ratio"] = match.group(1).strip()

        # Dividend yield
        match = re.search(r"Dividend yield:\s*(.+?)(?:\n|$)", text)
        if match:
            result["dividend_yield"] = match.group(1).strip()

        # DART 재무비율
        match = re.search(r"\[DART 재무비율[^\]]*?(\d{4})년\]", text)
        if match:
            result["dart_fiscal_year"] = match.group(1)

        match = re.search(r"ROE[^:]*:\s*([-\d\.]+)%", text)
        if match:
            try:
                result["dart_roe"] = float(match.group(1))
            except ValueError:
                pass

        match = re.search(r"ROA[^:]*:\s*([-\d\.]+)%", text)
        if match:
            try:
                result["dart_roa"] = float(match.group(1))
            except ValueError:
                pass

        match = re.search(r"부채비율:\s*([-\d\.]+)%", text)
        if match:
            try:
                result["dart_debt_ratio"] = float(match.group(1))
            except ValueError:
                pass

        match = re.search(r"매출액:\s*([-\d,\.]+)억원", text)
        if match:
            try:
                result["dart_sales"] = float(match.group(1).replace(",", "")) * 1e8
            except ValueError:
                pass

        match = re.search(r"영업이익:\s*([-\d,\.]+)억원", text)
        if match:
            try:
                result["dart_operating_income"] = float(match.group(1).replace(",", "")) * 1e8
            except ValueError:
                pass

        match = re.search(r"당기순이익:\s*([-\d,\.]+)억원", text)
        if match:
            try:
                result["dart_net_income"] = float(match.group(1).replace(",", "")) * 1e8
            except ValueError:
                pass

        return result
