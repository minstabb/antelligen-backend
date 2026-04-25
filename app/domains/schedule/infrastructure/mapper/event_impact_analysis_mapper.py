from app.domains.schedule.domain.entity.event_impact_analysis import EventImpactAnalysis
from app.domains.schedule.infrastructure.orm.event_impact_analysis_orm import (
    EventImpactAnalysisOrm,
)


class EventImpactAnalysisMapper:
    @staticmethod
    def to_entity(orm: EventImpactAnalysisOrm) -> EventImpactAnalysis:
        return EventImpactAnalysis(
            id=orm.id,
            event_id=orm.event_id,
            summary=orm.summary or "",
            direction=orm.direction or "neutral",
            impact_tags=list(orm.impact_tags or []),
            key_drivers=list(orm.key_drivers or []),
            risks=list(orm.risks or []),
            indicator_snapshot=dict(orm.indicator_snapshot or {}),
            model_name=orm.model_name or "",
            generated_at=orm.generated_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def to_new_orm(entity: EventImpactAnalysis) -> EventImpactAnalysisOrm:
        return EventImpactAnalysisOrm(
            event_id=entity.event_id,
            summary=entity.summary,
            direction=entity.direction,
            impact_tags=list(entity.impact_tags),
            key_drivers=list(entity.key_drivers),
            risks=list(entity.risks),
            indicator_snapshot=dict(entity.indicator_snapshot),
            model_name=entity.model_name,
            generated_at=entity.generated_at,
            updated_at=entity.updated_at,
        )
