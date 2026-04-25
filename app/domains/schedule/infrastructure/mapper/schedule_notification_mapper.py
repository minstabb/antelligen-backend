from app.domains.schedule.domain.entity.schedule_notification import ScheduleNotification
from app.domains.schedule.infrastructure.orm.schedule_notification_orm import (
    ScheduleNotificationOrm,
)


class ScheduleNotificationMapper:
    @staticmethod
    def to_entity(orm: ScheduleNotificationOrm) -> ScheduleNotification:
        return ScheduleNotification(
            id=orm.id,
            event_id=orm.event_id,
            event_title=orm.event_title or "",
            analysis_id=orm.analysis_id,
            success=orm.success,
            stored_at=orm.stored_at,
            error_message=orm.error_message or "",
            read_at=orm.read_at,
            created_at=orm.created_at,
        )

    @staticmethod
    def to_new_orm(entity: ScheduleNotification) -> ScheduleNotificationOrm:
        return ScheduleNotificationOrm(
            event_id=entity.event_id,
            event_title=entity.event_title,
            analysis_id=entity.analysis_id,
            success=entity.success,
            stored_at=entity.stored_at,
            error_message=entity.error_message,
            read_at=entity.read_at,
        )
