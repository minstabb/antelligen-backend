from abc import ABC, abstractmethod
from typing import List

from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar


class YahooFinancePort(ABC):
    @abstractmethod
    async def fetch_nasdaq_bars(self, period: str) -> List[NasdaqBar]:
        """yfinance에서 ^IXIC 나스닥 OHLCV 데이터를 수집한다.

        Args:
            period: yfinance period 문자열 (예: "1d", "5d", "1mo", "1y")

        Returns:
            NasdaqBar 엔티티 리스트

        Raises:
            NasdaqDataFetchException: 데이터 수집 실패 시
        """
        pass
