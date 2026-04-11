import hashlib
from datetime import datetime

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.news.application.port.user_saved_article_repository import UserSavedArticleRepository
from app.domains.news.domain.entity.user_saved_article import UserSavedArticle
from app.domains.news.infrastructure.orm.user_saved_article_orm import UserSavedArticleOrm


class UserSavedArticleRepositoryImpl(UserSavedArticleRepository):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save(self, article: UserSavedArticle) -> UserSavedArticle:
        link_hash = hashlib.sha256(article.link.encode()).hexdigest()
        orm = UserSavedArticleOrm(
            account_id=article.account_id,
            title=article.title,
            source=article.source,
            link=article.link,
            link_hash=link_hash,
            published_at=article.published_at,
            snippet=article.snippet,
            saved_at=datetime.now(),
        )
        self._db.add(orm)
        await self._db.commit()
        await self._db.refresh(orm)
        return self._to_entity(orm)

    async def find_by_user_and_link(self, account_id: int, link: str) -> UserSavedArticle | None:
        link_hash = hashlib.sha256(link.encode()).hexdigest()
        stmt = select(UserSavedArticleOrm).where(
            UserSavedArticleOrm.account_id == account_id,
            UserSavedArticleOrm.link_hash == link_hash,
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        return self._to_entity(orm) if orm else None

    async def find_by_id(self, article_id: int) -> UserSavedArticle | None:
        stmt = select(UserSavedArticleOrm).where(UserSavedArticleOrm.id == article_id)
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        return self._to_entity(orm) if orm else None

    async def find_all_by_user(self, account_id: int, page: int, page_size: int) -> tuple[list[UserSavedArticle], int]:
        offset = (page - 1) * page_size
        count_result = await self._db.execute(
            select(func.count()).select_from(UserSavedArticleOrm).where(UserSavedArticleOrm.account_id == account_id)
        )
        total = count_result.scalar_one()
        stmt = (
            select(UserSavedArticleOrm)
            .where(UserSavedArticleOrm.account_id == account_id)
            .order_by(UserSavedArticleOrm.saved_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self._db.execute(stmt)
        items = [self._to_entity(orm) for orm in result.scalars().all()]
        return items, total

    async def delete_by_id(self, article_id: int) -> None:
        stmt = delete(UserSavedArticleOrm).where(UserSavedArticleOrm.id == article_id)
        await self._db.execute(stmt)
        await self._db.commit()

    @staticmethod
    def _to_entity(orm: UserSavedArticleOrm) -> UserSavedArticle:
        return UserSavedArticle(
            article_id=orm.id,
            account_id=orm.account_id,
            title=orm.title,
            source=orm.source,
            link=orm.link,
            published_at=orm.published_at,
            snippet=orm.snippet,
            saved_at=orm.saved_at,
        )
