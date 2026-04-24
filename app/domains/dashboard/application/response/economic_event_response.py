from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.economic_event import EconomicEvent


class EconomicEventResponse(BaseModel):
    id: str
    type: str
    label: str
    date: date
    value: float
    previous: Optional[float]
    forecast: None = None

    @classmethod
    def from_entity(cls, entity: EconomicEvent) -> "EconomicEventResponse":
        return cls(
            id=entity.event_id,
            type=entity.type,
            label=entity.label,
            date=entity.date,
            value=entity.value,
            previous=entity.previous,
            forecast=None,
        )


class EconomicEventsResponse(BaseModel):
    period: str
    count: int
    events: List[EconomicEventResponse]
