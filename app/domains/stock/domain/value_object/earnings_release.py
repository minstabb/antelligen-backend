from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class EarningsRelease:
    """분기·잠정 실적 발표 값 객체 (KR + US 공통)"""
    ticker: str
    report_date: Optional[date] = None
    revenue: Optional[float] = None          # 매출액 (원 / USD)
    net_income: Optional[float] = None       # 당기순이익
    operating_income: Optional[float] = None # 영업이익
    eps: Optional[float] = None              # 주당순이익
    is_preliminary: bool = False             # True = 잠정실적(KR), False = 정식 발표(US)
    source: str = ""                         # 출처 (DART, yfinance, …)
    title: str = ""                          # 공시/리포트 제목
