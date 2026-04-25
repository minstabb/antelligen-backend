from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class EconomicEventItem(BaseModel):
    id: Optional[int] = None
    title: str
    country: str
    event_at: datetime
    importance: str
    description: str = ""
    reference_url: Optional[str] = None
    source: str


class SyncEconomicEventsResponse(BaseModel):
    fetched_count: int
    new_count: int
    duplicate_count: int
    start_date: str
    end_date: str


class GetEconomicEventsResponse(BaseModel):
    items: List[EconomicEventItem]
