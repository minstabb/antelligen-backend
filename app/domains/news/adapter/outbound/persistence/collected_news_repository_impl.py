import hashlib
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.news.application.port.collected_news_repository_port import CollectedNewsRepositoryPort
from app.domains.news.domain.entity.collected_news import CollectedNews
from app.domains.news.infrastructure.mapper.collected_news_mapper import CollectedNewsMapper
from app.domains.news.infrastructure.orm.collected_news_orm import CollectedNewsOrm


class CollectedNewsRepositoryImpl(CollectedNewsRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save(self, news: CollectedNews) -> CollectedNews:
        orm = CollectedNewsMapper.to_orm(news)
        self._db.add(orm)
        await self._db.commit()
        await self._db.refresh(orm)
        return CollectedNewsMapper.to_entity(orm)

    async def exists_by_url(self, url: str) -> bool:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        stmt = select(CollectedNewsOrm.id).where(CollectedNewsOrm.url_hash == url_hash)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_by_keyword(self, keyword: str, limit: int = 20) -> list[CollectedNews]:
        stmt = (
            select(CollectedNewsOrm)
            .where(CollectedNewsOrm.keyword == keyword)
            .order_by(CollectedNewsOrm.collected_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [CollectedNewsMapper.to_entity(orm) for orm in result.scalars().all()]

    async def find_all(self, limit: int = 100) -> list[CollectedNews]:
        stmt = (
            select(CollectedNewsOrm)
            .order_by(CollectedNewsOrm.collected_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [CollectedNewsMapper.to_entity(orm) for orm in result.scalars().all()]

    async def find_by_title_contains(self, keyword: str, limit: int = 10) -> list[CollectedNews]:
        stmt = (
            select(CollectedNewsOrm)
            .where(
                CollectedNewsOrm.title.ilike(f"%{keyword}%") |
                CollectedNewsOrm.description.ilike(f"%{keyword}%")
            )
            .order_by(CollectedNewsOrm.collected_at.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [CollectedNewsMapper.to_entity(orm) for orm in result.scalars().all()]

    async def has_recent_news(self, within_seconds: int) -> bool:
        cutoff = datetime.now() - timedelta(seconds=within_seconds)
        stmt = select(CollectedNewsOrm.id).where(CollectedNewsOrm.collected_at >= cutoff).limit(1)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None
