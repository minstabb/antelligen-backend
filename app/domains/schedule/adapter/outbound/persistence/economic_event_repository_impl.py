from datetime import date, datetime, time, timezone
from typing import List, Optional, Set

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.application.port.out.economic_event_repository_port import (
    EconomicEventRepositoryPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.infrastructure.mapper.economic_event_mapper import (
    EconomicEventMapper,
)
from app.domains.schedule.infrastructure.orm.economic_event_orm import EconomicEventOrm


class EconomicEventRepositoryImpl(EconomicEventRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def existing_source_ids(
        self, source: str, source_event_ids: List[str]
    ) -> Set[str]:
        if not source_event_ids:
            return set()
        stmt = select(EconomicEventOrm.source_event_id).where(
            and_(
                EconomicEventOrm.source == source,
                EconomicEventOrm.source_event_id.in_(source_event_ids),
            )
        )
        result = await self._db.execute(stmt)
        return set(result.scalars().all())

    async def save_all(self, events: List[EconomicEvent]) -> int:
        if not events:
            return 0
        orms = [EconomicEventMapper.to_new_orm(e) for e in events]
        self._db.add_all(orms)
        await self._db.commit()
        return len(orms)

    async def delete_by_source(self, source: str) -> int:
        stmt = delete(EconomicEventOrm).where(EconomicEventOrm.source == source)
        result = await self._db.execute(stmt)
        await self._db.commit()
        return int(result.rowcount or 0)

    async def find_by_source_key(
        self, source: str, source_event_id: str
    ) -> Optional[EconomicEvent]:
        stmt = select(EconomicEventOrm).where(
            and_(
                EconomicEventOrm.source == source,
                EconomicEventOrm.source_event_id == source_event_id,
            )
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        return EconomicEventMapper.to_entity(orm) if orm else None

    async def find_by_range(
        self,
        start: date,
        end: date,
        country: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> List[EconomicEvent]:
        start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
        conditions = [
            EconomicEventOrm.event_at >= start_dt,
            EconomicEventOrm.event_at <= end_dt,
        ]
        if country:
            conditions.append(EconomicEventOrm.country == country)
        if importance:
            conditions.append(EconomicEventOrm.importance == importance)

        stmt = (
            select(EconomicEventOrm)
            .where(and_(*conditions))
            .order_by(EconomicEventOrm.event_at.asc())
        )
        result = await self._db.execute(stmt)
        return [EconomicEventMapper.to_entity(orm) for orm in result.scalars().all()]
