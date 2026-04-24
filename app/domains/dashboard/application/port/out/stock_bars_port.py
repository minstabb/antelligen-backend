from abc import ABC, abstractmethod
from typing import List

from app.domains.dashboard.domain.entity.stock_bar import StockBar


class StockBarsPort(ABC):
    @abstractmethod
    async def fetch_stock_bars(self, ticker: str, period: str) -> tuple[str, List[StockBar]]:
        """yfinance에서 개별 종목 OHLCV 데이터를 수집한다.

        Args:
            ticker: 종목 코드 (예: "AAPL", "TSLA")
            period: yfinance period 문자열 (예: "1y", "5y", "max")

        Returns:
            (company_name, bars) 튜플

        Raises:
            InvalidTickerException: 존재하지 않는 ticker
            StockDataFetchException: 데이터 수집 실패
        """
        pass
