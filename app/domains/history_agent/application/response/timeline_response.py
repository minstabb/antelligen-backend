from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class HypothesisResult(BaseModel):
    hypothesis: str
    supporting_tools_called: List[str]


class TimelineEvent(BaseModel):
    title: str                           # AI 생성 이벤트 타이틀
    date: date
    category: str   # PRICE | CORPORATE | ANNOUNCEMENT | MACRO | NEWS
    type: str
    detail: str
    source: Optional[str] = None
    url: Optional[str] = None
    change_pct: Optional[float] = None   # PRICE 이벤트 변화율(%) — pre-filter 중요도 산정용
    causality: Optional[List[HypothesisResult]] = None
    # ETF holdings 분해 시 각 constituent 이벤트에 설정. ETF 자체 이벤트는 None.
    constituent_ticker: Optional[str] = None
    weight_pct: Optional[float] = None
    # 뉴스 이벤트용 감성 점수(-1..1). 소스에 따라 없을 수 있음.
    sentiment: Optional[float] = None
    # 매크로 이벤트 역사적 중요도(0..1). MACRO·MACRO_CONTEXT 이외엔 None.
    importance_score: Optional[float] = None


class TimelineResponse(BaseModel):
    # 매크로 전용 타임라인은 ticker 없이 region 기반으로도 반환된다.
    ticker: Optional[str] = None
    # ADR-0001: /timeline 은 chart_interval(봉 단위), /macro-timeline 은 lookback_range(조회 기간).
    # 시맨틱이 다르므로 단일 period 필드로 합치지 않고 각자 자기 엔드포인트에서만 채운다.
    chart_interval: Optional[str] = None
    lookback_range: Optional[str] = None
    count: int
    events: List[TimelineEvent]
    is_etf: bool = False
    # Literal 제한을 완화 — UNKNOWN이나 앞으로 추가될 원본 quote_type이 그대로 전달될 수 있도록.
    asset_type: str = "EQUITY"
    region: Optional[str] = None
