from abc import ABC, abstractmethod
from typing import List

from app.domains.dashboard.domain.entity.stock_bar import StockBar


class StockBarsPort(ABC):
    @abstractmethod
    async def fetch_stock_bars(
        self, ticker: str, chart_interval: str
    ) -> tuple[str, List[StockBar]]:
        """개별 종목 OHLCV 봉 데이터를 수집한다.

        Args:
            ticker: 종목 코드 (예: "AAPL", "005930", "^IXIC")
            chart_interval: 봉 단위 — "1D" | "1W" | "1M" | "1Q"
                (일/주/월/분기봉). lookback과 yfinance interval은 Adapter가 결정.

        Returns:
            (company_name, bars) 튜플

        Raises:
            InvalidTickerException: 존재하지 않는 ticker
            StockDataFetchException: 데이터 수집 실패
        """
        pass
