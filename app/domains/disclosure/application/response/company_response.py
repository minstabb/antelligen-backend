from typing import Optional

from pydantic import BaseModel


class CompanyResponse(BaseModel):
    company_id: int
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    market_type: Optional[str]
    market_cap_rank: Optional[int]
    is_top300: bool
    is_active: bool


class CompanyListResponse(BaseModel):
    companies: list[CompanyResponse]
    total_count: int


class CollectCompaniesResponse(BaseModel):
    total_fetched: int
    new_saved: int
    top300_updated: int
    message: str


