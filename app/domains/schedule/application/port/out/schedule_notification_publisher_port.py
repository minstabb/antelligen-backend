from abc import ABC, abstractmethod

from app.domains.schedule.domain.entity.schedule_notification import ScheduleNotification


class ScheduleNotificationPublisherPort(ABC):
    """저장 결과 알림을 영속화 + 실시간 채널로 발행한다."""

    @abstractmethod
    async def publish(self, notification: ScheduleNotification) -> ScheduleNotification:
        ...
