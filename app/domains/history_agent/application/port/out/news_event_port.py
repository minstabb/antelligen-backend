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
    ) -> List[NewsItem]:
        """지정 티커/지역에 대한 뉴스 아이템 리스트를 반환한다.

        실패/빈 결과는 빈 리스트로 graceful degradation.
        """
