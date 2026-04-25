from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.application.port.out.schedule_notification_repository_port import (
    ScheduleNotificationRepositoryPort,
)
from app.domains.schedule.domain.entity.schedule_notification import ScheduleNotification
from app.domains.schedule.infrastructure.mapper.schedule_notification_mapper import (
    ScheduleNotificationMapper,
)
from app.domains.schedule.infrastructure.orm.schedule_notification_orm import (
    ScheduleNotificationOrm,
)


class ScheduleNotificationRepositoryImpl(ScheduleNotificationRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def save(self, notification: ScheduleNotification) -> ScheduleNotification:
        orm = ScheduleNotificationMapper.to_new_orm(notification)
        self._db.add(orm)
        await self._db.commit()
        await self._db.refresh(orm)
        return ScheduleNotificationMapper.to_entity(orm)

    async def find_by_id(self, notification_id: int) -> Optional[ScheduleNotification]:
        stmt = select(ScheduleNotificationOrm).where(
            ScheduleNotificationOrm.id == notification_id
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        return ScheduleNotificationMapper.to_entity(orm) if orm else None

    async def list_recent(
        self, limit: int = 50, unread_only: bool = False
    ) -> List[ScheduleNotification]:
        stmt = select(ScheduleNotificationOrm).order_by(
            ScheduleNotificationOrm.created_at.desc()
        )
        if unread_only:
            stmt = stmt.where(ScheduleNotificationOrm.read_at.is_(None))
        stmt = stmt.limit(limit)
        result = await self._db.execute(stmt)
        return [
            ScheduleNotificationMapper.to_entity(orm) for orm in result.scalars().all()
        ]

    async def mark_read(self, notification_id: int) -> Optional[ScheduleNotification]:
        stmt = select(ScheduleNotificationOrm).where(
            ScheduleNotificationOrm.id == notification_id
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        if orm.read_at is None:
            orm.read_at = datetime.now(timezone.utc)
            await self._db.commit()
            await self._db.refresh(orm)
        return ScheduleNotificationMapper.to_entity(orm)

    async def mark_all_read(self) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            update(ScheduleNotificationOrm)
            .where(ScheduleNotificationOrm.read_at.is_(None))
            .values(read_at=now)
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return result.rowcount or 0
