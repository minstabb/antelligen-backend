from abc import ABC, abstractmethod

from app.domains.stock.domain.entity.stock_vector_document import StockVectorDocument
from app.domains.stock.domain.entity.stock_vector_store_result import (
    StockVectorStoreResult,
)


class StockVectorRepository(ABC):
    @abstractmethod
    async def save_documents(
        self,
        documents: list[StockVectorDocument],
    ) -> StockVectorStoreResult:
        pass
