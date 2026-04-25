from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ScheduleNotificationItem(BaseModel):
    id: Optional[int]
    event_id: int
    event_title: str
    analysis_id: Optional[int] = None
    success: bool
    stored_at: datetime
    error_message: str = ""
    read_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ListScheduleNotificationsResponse(BaseModel):
    unread_count: int
    total: int
    items: List[ScheduleNotificationItem]


class MarkScheduleNotificationReadResponse(BaseModel):
    id: int
    read_at: datetime


class MarkAllScheduleNotificationsReadResponse(BaseModel):
    updated_count: int
