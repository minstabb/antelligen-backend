from abc import ABC, abstractmethod

from app.domains.news.domain.entity.user_saved_article import UserSavedArticle


class UserSavedArticleRepository(ABC):

    @abstractmethod
    async def save(self, article: UserSavedArticle) -> UserSavedArticle:
        pass

    @abstractmethod
    async def find_by_user_and_link(self, account_id: int, link: str) -> UserSavedArticle | None:
        pass

    @abstractmethod
    async def find_by_id(self, article_id: int) -> UserSavedArticle | None:
        pass

    @abstractmethod
    async def find_all_by_user(self, account_id: int, page: int, page_size: int) -> tuple[list[UserSavedArticle], int]:
        pass

    @abstractmethod
    async def delete_by_id(self, article_id: int) -> None:
        pass
