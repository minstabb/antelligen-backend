from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel


class HypothesisResult(BaseModel):
    hypothesis: str
    supporting_tools_called: List[str]


class TimelineEvent(BaseModel):
    title: str                           # AI 생성 이벤트 타이틀
    date: date
    category: str   # PRICE | CORPORATE | ANNOUNCEMENT | MACRO
    type: str
    detail: str
    source: Optional[str] = None
    url: Optional[str] = None
    change_pct: Optional[float] = None   # PRICE 이벤트 변화율(%) — pre-filter 중요도 산정용
    causality: Optional[List[HypothesisResult]] = None


class TimelineResponse(BaseModel):
    ticker: str
    period: str
    count: int
    events: List[TimelineEvent]
    is_etf: bool = False
    asset_type: Literal["EQUITY", "INDEX", "ETF", "UNKNOWN"] = "EQUITY"
