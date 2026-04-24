from abc import ABC, abstractmethod

from app.domains.stock_theme.domain.entity.stock_theme import StockTheme


class StockThemeRepositoryPort(ABC):
    @abstractmethod
    async def save_all(self, stock_themes: list[StockTheme]) -> None:
        pass

    @abstractmethod
    async def find_all(self) -> list[StockTheme]:
        pass

    @abstractmethod
    async def exists_any(self) -> bool:
        pass
