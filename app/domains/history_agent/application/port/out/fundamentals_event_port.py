"""개별 종목 fundamentals 이벤트(애널리스트 레이팅 변동 / 실적 서프라이즈) 포트.

CORPORATE 카테고리 아래에 ANALYST_UPGRADE/DOWNGRADE, EARNINGS_BEAT/MISS 타입으로 매핑된다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Literal, Optional

FundamentalEventType = Literal[
    "ANALYST_UPGRADE",
    "ANALYST_DOWNGRADE",
    "EARNINGS_BEAT",
    "EARNINGS_MISS",
]


@dataclass
class FundamentalEvent:
    date: date
    type: FundamentalEventType
    detail: str
    source: str  # 예: "finnhub"
    change_pct: Optional[float] = None  # 실적 서프라이즈 %


class FundamentalsEventPort(ABC):
    @abstractmethod
    async def fetch_events(
        self, *, ticker: str, period: str
    ) -> List[FundamentalEvent]:
        """지정 기간의 fundamentals 이벤트 목록. 실패 시 빈 리스트."""
