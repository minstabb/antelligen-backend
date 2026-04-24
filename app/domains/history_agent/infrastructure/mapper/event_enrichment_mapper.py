from app.domains.history_agent.domain.entity.event_enrichment import EventEnrichment
from app.domains.history_agent.infrastructure.orm.event_enrichment_orm import EventEnrichmentOrm


class EventEnrichmentMapper:

    @staticmethod
    def to_entity(orm: EventEnrichmentOrm) -> EventEnrichment:
        return EventEnrichment(
            id=orm.id,
            ticker=orm.ticker,
            event_date=orm.event_date,
            event_type=orm.event_type,
            detail_hash=orm.detail_hash,
            title=orm.title,
            causality=orm.causality,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def to_orm(entity: EventEnrichment) -> EventEnrichmentOrm:
        return EventEnrichmentOrm(
            ticker=entity.ticker,
            event_date=entity.event_date,
            event_type=entity.event_type,
            detail_hash=entity.detail_hash,
            title=entity.title,
            causality=entity.causality,
        )
