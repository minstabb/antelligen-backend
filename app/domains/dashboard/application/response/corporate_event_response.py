from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.corporate_event import CorporateEvent


class CorporateEventResponse(BaseModel):
    date: date
    type: str
    detail: str
    source: str

    @classmethod
    def from_entity(cls, event: CorporateEvent) -> "CorporateEventResponse":
        return cls(
            date=event.date,
            type=event.type.value,
            detail=event.detail,
            source=event.source,
        )


class CorporateEventsResponse(BaseModel):
    ticker: str
    period: str
    count: int
    events: List[CorporateEventResponse]
