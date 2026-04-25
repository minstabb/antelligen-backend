from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.disclosure.application.port.collection_job_repository_port import (
    CollectionJobRepositoryPort,
)
from app.domains.disclosure.domain.entity.collection_job import CollectionJob
from app.domains.disclosure.domain.entity.collection_job_item import CollectionJobItem
from app.domains.disclosure.infrastructure.mapper.collection_job_mapper import (
    CollectionJobMapper,
    CollectionJobItemMapper,
)
from app.domains.disclosure.infrastructure.orm.collection_job_orm import CollectionJobOrm


class CollectionJobRepositoryImpl(CollectionJobRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save_job(self, job: CollectionJob) -> CollectionJob:
        orm = CollectionJobMapper.to_orm(job)
        self._db.add(orm)
        await self._db.commit()
        await self._db.refresh(orm)
        return CollectionJobMapper.to_entity(orm)

    async def update_job(self, job: CollectionJob) -> CollectionJob:
        await self._db.execute(
            update(CollectionJobOrm)
            .where(CollectionJobOrm.id == job.job_id)
            .values(
                finished_at=job.finished_at,
                status=job.status,
                collected_count=job.collected_count,
                saved_count=job.saved_count,
                message=job.message,
            )
        )
        await self._db.commit()
        return job

    async def save_items(self, items: list[CollectionJobItem]) -> int:
        if not items:
            return 0

        orm_list = [CollectionJobItemMapper.to_orm(item) for item in items]
        self._db.add_all(orm_list)
        await self._db.commit()
        return len(orm_list)

    async def find_latest_by_job_name(self, job_name: str) -> Optional[CollectionJob]:
        stmt = (
            select(CollectionJobOrm)
            .where(CollectionJobOrm.job_name == job_name)
            .order_by(CollectionJobOrm.started_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return CollectionJobMapper.to_entity(orm)
