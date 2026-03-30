from abc import ABC, abstractmethod
from typing import Optional

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

    @abstractmethod
    async def find_by_entity_id(
        self,
        entity_id: str,
    ) -> Optional[list[StockVectorDocument]]:
        """entity_id(ticker)로 저장된 문서를 조회합니다."""
        pass
