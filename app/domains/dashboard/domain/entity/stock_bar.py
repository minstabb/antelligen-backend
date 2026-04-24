from datetime import date
from typing import Optional


class StockBar:
    def __init__(
        self,
        bar_date: date,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        ticker: Optional[str] = None,
    ):
        self.ticker = ticker
        self.bar_date = bar_date
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
