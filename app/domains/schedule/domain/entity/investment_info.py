from dataclasses import dataclass
from datetime import datetime

from app.domains.schedule.domain.value_object.investment_info_type import InvestmentInfoType


@dataclass
class InvestmentInfo:
    info_type: InvestmentInfoType
    symbol: str
    value: float
    unit: str
    retrieved_at: datetime
    source: str
    description: str = ""
