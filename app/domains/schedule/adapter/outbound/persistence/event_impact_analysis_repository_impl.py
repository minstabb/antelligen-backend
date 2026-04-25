from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.application.port.out.event_impact_analysis_repository_port import (
    EventImpactAnalysisRepositoryPort,
)
from app.domains.schedule.domain.entity.event_impact_analysis import EventImpactAnalysis
from app.domains.schedule.infrastructure.mapper.event_impact_analysis_mapper import (
    EventImpactAnalysisMapper,
)
from app.domains.schedule.infrastructure.orm.event_impact_analysis_orm import (
    EventImpactAnalysisOrm,
)


class EventImpactAnalysisRepositoryImpl(EventImpactAnalysisRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def upsert(self, analysis: EventImpactAnalysis) -> EventImpactAnalysis:
        stmt = select(EventImpactAnalysisOrm).where(
            EventImpactAnalysisOrm.event_id == analysis.event_id
        )
        result = await self._db.execute(stmt)
        existing: Optional[EventImpactAnalysisOrm] = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing is None:
            orm = EventImpactAnalysisMapper.to_new_orm(analysis)
            orm.generated_at = analysis.generated_at or now
            orm.updated_at = now
            self._db.add(orm)
            await self._db.commit()
            await self._db.refresh(orm)
            return EventImpactAnalysisMapper.to_entity(orm)

        # 중복 → 갱신
        existing.summary = analysis.summary
        existing.direction = analysis.direction
        existing.impact_tags = list(analysis.impact_tags)
        existing.key_drivers = list(analysis.key_drivers)
        existing.risks = list(analysis.risks)
        existing.indicator_snapshot = dict(analysis.indicator_snapshot)
        existing.model_name = analysis.model_name
        existing.updated_at = now
        await self._db.commit()
        await self._db.refresh(existing)
        return EventImpactAnalysisMapper.to_entity(existing)

    async def find_by_event_id(self, event_id: int) -> Optional[EventImpactAnalysis]:
        stmt = select(EventImpactAnalysisOrm).where(
            EventImpactAnalysisOrm.event_id == event_id
        )
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        return EventImpactAnalysisMapper.to_entity(orm) if orm else None

    async def find_by_event_ids(self, event_ids: List[int]) -> List[EventImpactAnalysis]:
        if not event_ids:
            return []
        stmt = select(EventImpactAnalysisOrm).where(
            EventImpactAnalysisOrm.event_id.in_(event_ids)
        )
        result = await self._db.execute(stmt)
        return [
            EventImpactAnalysisMapper.to_entity(orm)
            for orm in result.scalars().all()
        ]
