from dataclasses import dataclass
from datetime import date
from enum import Enum


class PriceEventType(str, Enum):
    HIGH_52W = "HIGH_52W"        # 52주 신고가
    LOW_52W = "LOW_52W"          # 52주 신저가
    SURGE = "SURGE"              # +5% 이상 급등
    PLUNGE = "PLUNGE"            # -5% 이상 급락
    GAP_UP = "GAP_UP"            # 갭 상승
    GAP_DOWN = "GAP_DOWN"        # 갭 하락


@dataclass
class PriceEvent:
    date: date
    type: PriceEventType
    value: float   # 이벤트의 핵심 수치 (변화율 %, 배수 등)
    detail: str    # 사람이 읽을 수 있는 설명
