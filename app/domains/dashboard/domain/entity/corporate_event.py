from dataclasses import dataclass
from datetime import date
from enum import Enum


class CorporateEventType(str, Enum):
    STOCK_SPLIT = "STOCK_SPLIT"            # 주식 분할
    RIGHTS_OFFERING = "RIGHTS_OFFERING"    # 유상증자
    BUYBACK = "BUYBACK"                    # 자사주 매입
    BUYBACK_CANCEL = "BUYBACK_CANCEL"      # 자사주 소각
    DISCLOSURE = "DISCLOSURE"              # 기타 주요 공시


@dataclass
class CorporateEvent:
    date: date
    type: CorporateEventType
    detail: str
    source: str  # "yfinance" | "dart"
