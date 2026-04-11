from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.news.application.port.article_content_repository import ArticleContentRepository
from app.domains.news.infrastructure.orm.article_content_orm import ArticleContentOrm


class ArticleContentRepositoryImpl(ArticleContentRepository):
    def __init__(self, vector_db: AsyncSession):
        self._db = vector_db

    async def save(self, user_saved_article_id: int, content: str | None, snippet: str | None) -> None:
        payload: dict = {}
        if content:
            payload["scraped_content"] = content
        if snippet:
            payload["snippet"] = snippet

        orm = ArticleContentOrm(
            user_saved_article_id=user_saved_article_id,
            content=payload or None,
        )
        self._db.add(orm)
        await self._db.commit()
