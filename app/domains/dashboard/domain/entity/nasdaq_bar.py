from datetime import date
from typing import Optional


class NasdaqBar:
    def __init__(
        self,
        bar_date: date,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        bar_id: Optional[int] = None,
    ):
        self.bar_id = bar_id
        self.bar_date = bar_date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
