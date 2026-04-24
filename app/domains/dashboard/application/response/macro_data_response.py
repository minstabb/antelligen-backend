from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.dashboard.domain.entity.macro_data_point import MacroDataPoint


class MacroDataPointResponse(BaseModel):
    date: date
    value: float

    @classmethod
    def from_entity(cls, entity: MacroDataPoint) -> "MacroDataPointResponse":
        return cls(date=entity.date, value=entity.value)


class MacroDataResponse(BaseModel):
    period: str
    interestRate: List[MacroDataPointResponse]
    cpi: List[MacroDataPointResponse]
    unemployment: List[MacroDataPointResponse]
