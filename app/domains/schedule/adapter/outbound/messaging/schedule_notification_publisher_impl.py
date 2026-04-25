"""저장 + 브로드캐스트 두 작업을 묶은 ScheduleNotificationPublisher 구현.

DB 에 영속화한 뒤 같은 payload 를 SSE 브로드캐스터로 publish 한다.
DB 저장이 실패해도 브로드캐스트는 최선으로 수행한다.
"""

import logging

from app.domains.schedule.adapter.outbound.messaging.notification_broadcaster import (
    NotificationBroadcaster,
)
from app.domains.schedule.application.port.out.schedule_notification_publisher_port import (
    ScheduleNotificationPublisherPort,
)
from app.domains.schedule.application.port.out.schedule_notification_repository_port import (
    ScheduleNotificationRepositoryPort,
)
from app.domains.schedule.domain.entity.schedule_notification import ScheduleNotification

logger = logging.getLogger(__name__)


class ScheduleNotificationPublisher(ScheduleNotificationPublisherPort):
    def __init__(
        self,
        repository: ScheduleNotificationRepositoryPort,
        broadcaster: NotificationBroadcaster,
    ):
        self._repository = repository
        self._broadcaster = broadcaster

    async def publish(self, notification: ScheduleNotification) -> ScheduleNotification:
        print(
            f"[schedule.publisher] ▶ 알림 발행 event_id={notification.event_id} "
            f"success={notification.success}"
        )

        saved = notification
        try:
            saved = await self._repository.save(notification)
            print(
                f"[schedule.publisher]   ✓ DB 저장 완료 id={saved.id} "
                f"read_at={saved.read_at}"
            )
        except Exception as exc:
            print(f"[schedule.publisher]   ❌ DB 저장 실패: {exc}")
            logger.exception("[schedule.publisher] DB 저장 실패: %s", exc)

        # SSE 브로드캐스트 payload
        payload = {
            "id": saved.id,
            "event_id": saved.event_id,
            "event_title": saved.event_title,
            "analysis_id": saved.analysis_id,
            "success": saved.success,
            "stored_at": saved.stored_at.isoformat() if saved.stored_at else None,
            "error_message": saved.error_message,
            "read_at": saved.read_at.isoformat() if saved.read_at else None,
        }
        try:
            await self._broadcaster.publish(payload)
            print("[schedule.publisher]   ✓ SSE broadcast 완료")
        except Exception as exc:
            print(f"[schedule.publisher]   ❌ SSE broadcast 실패: {exc}")
            logger.exception("[schedule.publisher] broadcast 실패: %s", exc)

        return saved
