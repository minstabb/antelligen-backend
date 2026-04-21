from abc import ABC, abstractmethod


class TickerKeywordResolverPort(ABC):

    @abstractmethod
    async def resolve(self, ticker: str) -> list[str]:
        """종목코드 → 검색 키워드 목록 반환. 결과 없으면 빈 리스트."""
        pass
