"""History Agent 뉴스 수집용 포트.

adapter/outbound 에서 Finnhub/GDELT/Yahoo/Naver 등을 조합해 구현한다.
Application 레이어는 포트만 의존한다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Literal, Optional

Region = Literal["US", "KR", "GLOBAL"]


@dataclass
class NewsItem:
    date: date
    title: str
    url: str
    source: str  # "finnhub" | "gdelt" | "yahoo" | "naver"
    summary: Optional[str] = None
    sentiment: Optional[float] = None


class NewsEventPort(ABC):
    @abstractmethod
    async def fetch_news(
        self,
        *,
        ticker: str,
        period: str,
        region: Region,
        top_n: int = 10,
        lookback_days: Optional[int] = None,
    ) -> List[NewsItem]:
        """지정 티커/지역에 대한 뉴스 아이템 리스트를 반환한다.

        `lookback_days` 가 주어지면 `period` lookup 보다 우선 적용 (§13.4 B).
        chart_interval 기반 timeline 호출은 봉 단위 차트 범위에 맞는 윈도우를
        명시적으로 전달해야 한다.

        실패/빈 결과는 빈 리스트로 graceful degradation.
        """
