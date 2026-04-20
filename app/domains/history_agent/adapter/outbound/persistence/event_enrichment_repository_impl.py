from datetime import date
from typing import List, Tuple

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.domain.entity.event_enrichment import EventEnrichment
from app.domains.history_agent.infrastructure.mapper.event_enrichment_mapper import (
    EventEnrichmentMapper,
)
from app.domains.history_agent.infrastructure.orm.event_enrichment_orm import EventEnrichmentOrm


class EventEnrichmentRepositoryImpl(EventEnrichmentRepositoryPort):

    def __init__(self, db: AsyncSession):
        self._db = db

    async def find_by_keys(
        self, keys: List[Tuple[str, date, str, str]]
    ) -> List[EventEnrichment]:
        if not keys:
            return []

        stmt = select(EventEnrichmentOrm).where(
            tuple_(
                EventEnrichmentOrm.ticker,
                EventEnrichmentOrm.event_date,
                EventEnrichmentOrm.event_type,
                EventEnrichmentOrm.detail_hash,
            ).in_(keys)
        )
        result = await self._db.execute(stmt)
        return [EventEnrichmentMapper.to_entity(orm) for orm in result.scalars().all()]

    async def upsert_bulk(self, enrichments: List[EventEnrichment]) -> int:
        if not enrichments:
            return 0

        values = [
            {
                "ticker": e.ticker,
                "event_date": e.event_date,
                "event_type": e.event_type,
                "detail_hash": e.detail_hash,
                "title": e.title,
                "causality": e.causality,
            }
            for e in enrichments
        ]

        excluded = insert(EventEnrichmentOrm).excluded
        stmt = (
            insert(EventEnrichmentOrm)
            .values(values)
            .on_conflict_do_update(
                constraint="uq_event_enrichments_key",
                set_={
                    "title": excluded.title,
                    "causality": excluded.causality,
                    "updated_at": excluded.updated_at,
                },
            )
            .returning(EventEnrichmentOrm.id)
        )

        result = await self._db.execute(stmt)
        await self._db.commit()
        return len(result.fetchall())
