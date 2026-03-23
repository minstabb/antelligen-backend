from abc import ABC, abstractmethod

from app.domains.stock.domain.entity.collected_stock_data import CollectedStockData
from app.domains.stock.domain.entity.raw_collected_stock_data import (
    RawCollectedStockData,
)


class StockDataStandardizer(ABC):
    @abstractmethod
    def standardize(
        self, raw_data: RawCollectedStockData
    ) -> CollectedStockData | None:
        pass
