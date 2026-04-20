from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.price_event import PriceEvent


class PriceEventResponse(BaseModel):
    date: date
    type: str
    value: float
    detail: str

    @classmethod
    def from_entity(cls, event: PriceEvent) -> "PriceEventResponse":
        return cls(
            date=event.date,
            type=event.type.value,
            value=event.value,
            detail=event.detail,
        )


class PriceEventsResponse(BaseModel):
    ticker: str
    period: str
    count: int
    events: List[PriceEventResponse]
