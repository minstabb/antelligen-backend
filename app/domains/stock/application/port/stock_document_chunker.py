from abc import ABC, abstractmethod

from app.domains.stock.domain.entity.stock_document_chunk import StockDocumentChunk


class StockDocumentChunker(ABC):
    @abstractmethod
    def chunk(
        self,
        *,
        entity_id: str,
        source: str,
        dedup_key: str,
        document_text: str,
    ) -> list[StockDocumentChunk]:
        pass
