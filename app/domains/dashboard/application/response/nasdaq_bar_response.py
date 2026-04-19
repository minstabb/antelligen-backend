from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar


class NasdaqBarResponse(BaseModel):
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_entity(cls, entity: NasdaqBar) -> "NasdaqBarResponse":
        return cls(
            bar_date=entity.bar_date,
            open=entity.open,
            high=entity.high,
            low=entity.low,
            close=entity.close,
            volume=entity.volume,
        )


class NasdaqBarsResponse(BaseModel):
    period: str
    count: int
    bars: List[NasdaqBarResponse]
