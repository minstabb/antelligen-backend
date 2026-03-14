from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.post.application.port.post_repository import PostRepository
from app.domains.post.domain.entity.post import Post
from app.domains.post.infrastructure.mapper.post_mapper import PostMapper
from app.domains.post.infrastructure.orm.post_orm import PostOrm


class PostRepositoryImpl(PostRepository):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save(self, post: Post) -> Post:
        orm = PostMapper.to_orm(post)
        self._db.add(orm)
        await self._db.commit()
        await self._db.refresh(orm)
        return PostMapper.to_entity(orm)
