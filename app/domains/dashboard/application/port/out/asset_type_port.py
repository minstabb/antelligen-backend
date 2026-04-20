from abc import ABC, abstractmethod


class AssetTypePort(ABC):
    @abstractmethod
    async def get_quote_type(self, ticker: str) -> str:
        """티커의 자산 유형 문자열을 반환한다.

        Returns:
            yfinance quoteType 값. 예: "EQUITY", "ETF", "INDEX", "MUTUALFUND".
            조회 실패 시 "UNKNOWN".
        """
        pass

    async def is_etf(self, ticker: str) -> bool:
        quote_type = await self.get_quote_type(ticker)
        return quote_type.upper() == "ETF"
