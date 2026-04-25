from datetime import datetime
from typing import List

from pydantic import BaseModel


class InvestmentInfoItem(BaseModel):
    info_type: str
    display_name: str
    symbol: str
    value: float
    unit: str
    retrieved_at: datetime
    source: str
    description: str = ""


class SearchInvestmentInfoResponse(BaseModel):
    items: List[InvestmentInfoItem]
