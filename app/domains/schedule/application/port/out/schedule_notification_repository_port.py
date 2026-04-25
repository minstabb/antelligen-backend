from abc import ABC, abstractmethod
from typing import List, Optional

from app.domains.schedule.domain.entity.schedule_notification import ScheduleNotification


class ScheduleNotificationRepositoryPort(ABC):
    @abstractmethod
    async def save(self, notification: ScheduleNotification) -> ScheduleNotification:
        ...

    @abstractmethod
    async def find_by_id(self, notification_id: int) -> Optional[ScheduleNotification]:
        ...

    @abstractmethod
    async def list_recent(
        self, limit: int = 50, unread_only: bool = False
    ) -> List[ScheduleNotification]:
        ...

    @abstractmethod
    async def mark_read(self, notification_id: int) -> Optional[ScheduleNotification]:
        ...

    @abstractmethod
    async def mark_all_read(self) -> int:
        ...
