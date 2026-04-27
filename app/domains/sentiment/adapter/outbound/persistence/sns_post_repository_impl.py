"""
SnsPostRepositoryImpl
=====================
SnsPostRepositoryPort의 SQLAlchemy AsyncSession 구현체.
CollectedNewsRepositoryImpl 패턴 그대로 따름.

주요 차이점:
- 중복 키: url_hash 대신 post_hash (sha256(platform + post_id))
- save_batch: 여러 건 일괄 저장 + IntegrityError 캐치 → skip
- find_by_ticker: ticker 기준 조회, platform 옵션 필터
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sentiment.application.port.sns_post_repository_port import SnsPostRepositoryPort
from app.domains.sentiment.domain.entity.sns_post import SnsPost
from app.domains.sentiment.infrastructure.mapper.sns_post_mapper import SnsPostMapper
from app.domains.sentiment.infrastructure.orm.sns_post_orm import SnsPostOrm

logger = logging.getLogger(__name__)


class SnsPostRepositoryImpl(SnsPostRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save(self, post: SnsPost) -> SnsPost:
        """게시물 저장. 저장 후 id가 채워진 Entity 반환."""
        orm = SnsPostMapper.to_orm(post)
        self._db.add(orm)
        await self._db.commit()
        await self._db.refresh(orm)
        return SnsPostMapper.to_entity(orm)

    async def save_batch(self, posts: list[SnsPost]) -> int:
        """
        여러 건 일괄 저장.
        post_hash 중복(IntegrityError)은 skip 처리.
        Returns: 실제로 저장된 개수.
        """
        saved_count = 0
        for post in posts:
            try:
                orm = SnsPostMapper.to_orm(post)
                self._db.add(orm)
                await self._db.flush()   # 개별 flush로 IntegrityError 즉시 감지
                saved_count += 1
            except IntegrityError:
                # post_hash 또는 (platform, post_id) 중복 → skip
                await self._db.rollback()
                logger.debug(
                    f"SnsPost 중복 skip: platform={post.platform}, post_id={post.post_id}"
                )

        if saved_count > 0:
            await self._db.commit()

        return saved_count

    async def exists_by_hash(self, post_hash: str) -> bool:
        """post_hash 기준 중복 체크."""
        stmt = select(SnsPostOrm.id).where(SnsPostOrm.post_hash == post_hash)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_by_ticker(
        self,
        ticker: str,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> list[SnsPost]:
        """
        종목 티커로 조회.
        platform 지정 시 해당 플랫폼만 필터링.
        최신순(collected_at desc) 정렬.
        """
        stmt = (
            select(SnsPostOrm)
            .where(SnsPostOrm.ticker == ticker)
            .order_by(SnsPostOrm.collected_at.desc())
            .limit(limit)
        )
        if platform:
            stmt = stmt.where(SnsPostOrm.platform == platform)

        result = await self._db.execute(stmt)
        return [SnsPostMapper.to_entity(orm) for orm in result.scalars().all()]

    async def count_by_ticker(self, ticker: str) -> int:
        """해당 티커의 게시물 총 개수."""
        stmt = select(func.count()).where(SnsPostOrm.ticker == ticker)
        result = await self._db.execute(stmt)
        return result.scalar_one()
