from datetime import date
from typing import Optional


class EconomicEvent:
    def __init__(
        self,
        event_id: str,
        type: str,
        label: str,
        date: date,
        value: float,
        previous: Optional[float],
        forecast: None = None,
    ):
        self.event_id = event_id
        self.type = type
        self.label = label
        self.date = date
        self.value = value
        self.previous = previous
        self.forecast = forecast
