from datetime import datetime

from pydantic import BaseModel


class StockCollectionMetadataResponse(BaseModel):
    entity_id: str
    source: str
    collected_at: datetime
    dedup_key: str
    dedup_basis: str
    reference_url: str | None = None


class StockBasicInformationResponse(BaseModel):
    ticker: str
    stock_name: str
    market: str
    company_summary: str | None = None


class StockFinancialInformationResponse(BaseModel):
    current_price: str | None = None
    currency: str | None = None
    market_cap: str | None = None
    pe_ratio: str | None = None
    dividend_yield: str | None = None


class StockIngestionReadyDataResponse(BaseModel):
    entity_id: str
    source: str
    collected_at: datetime
    dedup_key: str
    collected_types: list[str]
    content: str


class StockDocumentChunkResponse(BaseModel):
    chunk_id: str
    chunk_index: int
    content: str
    start_char: int
    end_char: int
    embedding_vector: list[float]


class StockVectorStoreResultResponse(BaseModel):
    total_chunk_count: int
    stored_chunk_count: int
    skipped_chunk_count: int
    duplicate_prevented: bool


class StockCollectionResponse(BaseModel):
    ticker: str
    stock_name: str
    market: str
    collected_types: list[str]
    metadata: StockCollectionMetadataResponse
    ingestion_ready_data: StockIngestionReadyDataResponse
    basic_information: StockBasicInformationResponse | None = None
    financial_information: StockFinancialInformationResponse | None = None
    document_text: str | None = None
    document_chunks: list[StockDocumentChunkResponse]
    vector_store_result: StockVectorStoreResultResponse
