"""매크로 지표(관련 자산·지정학 리스크) 이벤트 포트.

INDEX/ETF 경로에서 PRICE + FRED MACRO 외 부차 context 로 사용된다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Literal, Optional


MacroContextType = Literal[
    "VIX_SPIKE",
    "OIL_SPIKE",
    "GOLD_SPIKE",
    "US10Y_SPIKE",
    "FX_MOVE",
    "GEOPOLITICAL_RISK",
]


@dataclass
class MacroContextEvent:
    date: date
    type: MacroContextType
    label: str  # 사람이 읽을 라벨 (예: "VIX 급등")
    detail: str
    change_pct: Optional[float] = None
    source: str = "related_assets"


class RelatedAssetsPort(ABC):
    @abstractmethod
    async def fetch_significant_moves(
        self, *, start_date: date, end_date: date, threshold_pct: float
    ) -> List[MacroContextEvent]:
        """임계치를 넘은 일일 변동 이벤트. 실패 시 빈 리스트."""


class GprIndexPort(ABC):
    @abstractmethod
    async def fetch_mom_spikes(
        self, *, start_date: date, end_date: date, mom_change_pct: float
    ) -> List[MacroContextEvent]:
        """전월 대비 GPR 지수가 mom_change_pct% 이상 상승한 달. 실패 시 빈 리스트."""
