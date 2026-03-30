from abc import ABC, abstractmethod

from app.domains.stock.domain.entity.collected_stock_data import CollectedStockData
from app.domains.stock.domain.entity.raw_collected_stock_data import (
    RawCollectedStockData,
)


class StockDataStandardizer(ABC):
    @abstractmethod
    def standardize(
        self,
        raw_data: RawCollectedStockData,
        dart_roe: float | None = None,
        dart_roa: float | None = None,
        dart_debt_ratio: float | None = None,
        dart_fiscal_year: str | None = None,
    ) -> CollectedStockData | None:
        pass
