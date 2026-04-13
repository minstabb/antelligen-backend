from sqlalchemy import select
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

    async def find_by_article_id(self, user_saved_article_id: int) -> str | None:
        stmt = select(ArticleContentOrm).where(
            ArticleContentOrm.user_saved_article_id == user_saved_article_id
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None or not orm.content:
            return None
        return orm.content.get("scraped_content")
