from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.domain.value_object.event_importance import EventImportance
from app.domains.schedule.infrastructure.orm.economic_event_orm import EconomicEventOrm


class EconomicEventMapper:
    @staticmethod
    def to_entity(orm: EconomicEventOrm) -> EconomicEvent:
        return EconomicEvent(
            id=orm.id,
            source=orm.source,
            source_event_id=orm.source_event_id,
            title=orm.title,
            country=orm.country,
            event_at=orm.event_at,
            importance=EventImportance.parse(orm.importance),
            description=orm.description or "",
            reference_url=orm.reference_url,
        )

    @staticmethod
    def to_new_orm(entity: EconomicEvent) -> EconomicEventOrm:
        return EconomicEventOrm(
            source=entity.source,
            source_event_id=entity.source_event_id,
            title=entity.title,
            country=entity.country,
            event_at=entity.event_at,
            importance=entity.importance.value,
            description=entity.description or "",
            reference_url=entity.reference_url,
        )
