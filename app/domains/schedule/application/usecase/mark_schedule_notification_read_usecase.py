from app.common.exception.app_exception import AppException
from app.domains.schedule.application.port.out.schedule_notification_repository_port import (
    ScheduleNotificationRepositoryPort,
)
from app.domains.schedule.application.response.schedule_notification_response import (
    MarkAllScheduleNotificationsReadResponse,
    MarkScheduleNotificationReadResponse,
)


class MarkScheduleNotificationReadUseCase:
    def __init__(self, repository: ScheduleNotificationRepositoryPort):
        self._repository = repository

    async def execute_single(
        self, notification_id: int
    ) -> MarkScheduleNotificationReadResponse:
        print(f"[schedule.notifications.read] id={notification_id}")
        updated = await self._repository.mark_read(notification_id)
        if updated is None or updated.read_at is None:
            raise AppException(
                status_code=404,
                message=f"알림을 찾을 수 없습니다: id={notification_id}",
            )
        print(
            f"[schedule.notifications.read] ✓ id={updated.id} read_at={updated.read_at}"
        )
        return MarkScheduleNotificationReadResponse(
            id=updated.id, read_at=updated.read_at
        )

    async def execute_all(self) -> MarkAllScheduleNotificationsReadResponse:
        print("[schedule.notifications.read] mark_all_read")
        count = await self._repository.mark_all_read()
        print(f"[schedule.notifications.read] ✓ updated={count}")
        return MarkAllScheduleNotificationsReadResponse(updated_count=count)
