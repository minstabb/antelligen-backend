from abc import ABC, abstractmethod


class ArticleContentRepository(ABC):

    @abstractmethod
    async def save(self, user_saved_article_id: int, content: str | None, snippet: str | None) -> None:
        pass
