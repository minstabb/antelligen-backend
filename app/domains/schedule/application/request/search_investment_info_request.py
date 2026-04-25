from typing import List

from pydantic import BaseModel, Field


class SearchInvestmentInfoRequest(BaseModel):
    """하나 이상의 투자 정보 유형을 지정한다.

    예: { "types": ["interest_rate", "oil_price", "exchange_rate"] } 또는 ["금리", "유가", "환율"]
    """

    types: List[str] = Field(..., min_length=1, description="investment info types")
