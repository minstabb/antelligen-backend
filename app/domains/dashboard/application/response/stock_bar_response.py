from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.stock_bar import StockBar


class StockBarResponse(BaseModel):
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_entity(cls, entity: StockBar) -> "StockBarResponse":
        return cls(
            bar_date=entity.bar_date,
            open=entity.open,
            high=entity.high,
            low=entity.low,
            close=entity.close,
            volume=entity.volume,
        )


class StockBarsResponse(BaseModel):
    ticker: str
    company_name: str
    period: str
    count: int
    bars: List[StockBarResponse]
