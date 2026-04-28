"""
SnsPost Mapper
==============
ORM(infrastructure) ↔ Entity(domain) 변환.
news 도메인의 collected_news_mapper 패턴 그대로.
"""

from app.domains.sentiment.domain.entity.sns_post import SnsPost
from app.domains.sentiment.infrastructure.orm.sns_post_orm import SnsPostOrm


class SnsPostMapper:
    """ORM ↔ Entity 양방향 변환기"""

    @staticmethod
    def to_entity(orm: SnsPostOrm) -> SnsPost:
        """ORM → Entity (DB에서 읽어와서 도메인 로직에 넘길 때)"""
        return SnsPost(
            id=orm.id,
            platform=orm.platform,
            post_id=orm.post_id,
            post_hash=orm.post_hash,
            ticker=orm.ticker,
            title=orm.title,
            content=orm.content,
            url=orm.url,
            author=orm.author,
            score=orm.score,
            comment_count=orm.comment_count,
            extra_meta=orm.extra_meta,
            posted_at=orm.posted_at,
            collected_at=orm.collected_at,
        )

    @staticmethod
    def to_orm(entity: SnsPost) -> SnsPostOrm:
        """Entity → ORM (DB에 저장할 때)"""
        return SnsPostOrm(
            id=entity.id,
            platform=entity.platform,
            post_id=entity.post_id,
            post_hash=entity.post_hash,
            ticker=entity.ticker,
            title=entity.title,
            content=entity.content,
            url=entity.url,
            author=entity.author,
            score=entity.score,
            comment_count=entity.comment_count,
            extra_meta=entity.extra_meta,
            posted_at=entity.posted_at,
            collected_at=entity.collected_at,
        )
