from abc import ABC, abstractmethod


class ArticleContentRepository(ABC):

    @abstractmethod
    async def save(self, user_saved_article_id: int, content: str | None, snippet: str | None) -> None:
        pass

    @abstractmethod
    async def find_by_article_id(self, user_saved_article_id: int) -> str | None:
        """저장된 기사 본문을 반환한다. 없으면 None."""
        pass
