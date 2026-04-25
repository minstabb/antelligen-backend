from abc import ABC, abstractmethod

from app.domains.news.domain.entity.collected_news import CollectedNews


class CollectedNewsRepositoryPort(ABC):

    @abstractmethod
    async def save(self, news: CollectedNews) -> CollectedNews:
        pass

    @abstractmethod
    async def exists_by_url(self, url: str) -> bool:
        pass

    @abstractmethod
    async def find_by_keyword(self, keyword: str, limit: int = 20) -> list[CollectedNews]:
        pass

    @abstractmethod
    async def find_all(self, limit: int = 100) -> list[CollectedNews]:
        pass

    @abstractmethod
    async def find_by_title_contains(self, keyword: str, limit: int = 10) -> list[CollectedNews]:
        pass

    @abstractmethod
    async def has_recent_news(self, within_seconds: int) -> bool:
        pass
