from app.domains.schedule.application.port.out.schedule_notification_repository_port import (
    ScheduleNotificationRepositoryPort,
)
from app.domains.schedule.application.response.schedule_notification_response import (
    ListScheduleNotificationsResponse,
    ScheduleNotificationItem,
)


class ListScheduleNotificationsUseCase:
    def __init__(self, repository: ScheduleNotificationRepositoryPort):
        self._repository = repository

    async def execute(
        self, limit: int = 50, unread_only: bool = False
    ) -> ListScheduleNotificationsResponse:
        print(
            f"[schedule.notifications.list] limit={limit} unread_only={unread_only}"
        )
        items = await self._repository.list_recent(limit=limit, unread_only=unread_only)
        unread = [it for it in items if it.read_at is None]
        print(
            f"[schedule.notifications.list] total={len(items)} unread={len(unread)}"
        )
        return ListScheduleNotificationsResponse(
            unread_count=len(unread),
            total=len(items),
            items=[
                ScheduleNotificationItem(
                    id=it.id,
                    event_id=it.event_id,
                    event_title=it.event_title,
                    analysis_id=it.analysis_id,
                    success=it.success,
                    stored_at=it.stored_at,
                    error_message=it.error_message,
                    read_at=it.read_at,
                    created_at=it.created_at,
                )
                for it in items
            ],
        )
