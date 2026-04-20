from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.announcement_event import AnnouncementEvent


class AnnouncementEventResponse(BaseModel):
    date: date
    type: str
    title: str
    source: str
    url: str

    @classmethod
    def from_entity(cls, event: AnnouncementEvent) -> "AnnouncementEventResponse":
        return cls(
            date=event.date,
            type=event.type.value,
            title=event.title,
            source=event.source,
            url=event.url,
        )


class AnnouncementsResponse(BaseModel):
    ticker: str
    period: str
    count: int
    events: List[AnnouncementEventResponse]
