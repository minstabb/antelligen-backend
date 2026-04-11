from abc import ABC, abstractmethod

from app.domains.news.domain.entity.saved_article import SavedArticle


class SavedArticleRepository(ABC):

    @abstractmethod
    async def save(self, article: SavedArticle) -> SavedArticle:
        pass

    @abstractmethod
    async def find_by_id(self, article_id: int) -> SavedArticle | None:
        pass

    @abstractmethod
    async def find_by_link(self, link: str) -> SavedArticle | None:
        pass

    @abstractmethod
    async def find_all(self, page: int, page_size: int) -> tuple[list[SavedArticle], int]:
        pass
