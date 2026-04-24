from abc import ABC, abstractmethod
from typing import List

from app.domains.market_analysis.domain.service.context_builder import KeywordItem, StockThemeItem


class MarketContextPort(ABC):
    @abstractmethod
    async def get_top_keywords(self, top_n: int) -> List[KeywordItem]:
        pass

    @abstractmethod
    async def get_stock_themes(self) -> List[StockThemeItem]:
        pass
