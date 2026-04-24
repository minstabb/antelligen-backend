from abc import ABC, abstractmethod

from app.domains.stock_theme.domain.entity.defense_stock import DefenseStock


class MarketDataPort(ABC):
    @abstractmethod
    async def fetch_all_defense_stocks(self) -> list[DefenseStock]:
        pass
