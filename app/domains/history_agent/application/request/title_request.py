from datetime import date
from typing import List

from pydantic import BaseModel, Field


class TitleEventRequest(BaseModel):
    date: date
    type: str = Field(..., min_length=1)
    detail: str = Field(..., min_length=1)


class TitleBatchRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    events: List[TitleEventRequest] = Field(..., max_length=50)
