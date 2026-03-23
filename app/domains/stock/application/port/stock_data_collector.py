from abc import ABC, abstractmethod

from app.domains.stock.domain.entity.raw_collected_stock_data import RawCollectedStockData


class StockDataCollector(ABC):
    @abstractmethod
    async def collect(
        self, ticker: str, stock_name: str, market: str
    ) -> RawCollectedStockData | None:
        pass
