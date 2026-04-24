from abc import ABC, abstractmethod
from typing import List

from app.domains.dashboard.domain.entity.corporate_event import CorporateEvent


class YahooFinanceCorporateEventPort(ABC):
    @abstractmethod
    async def fetch_corporate_events(self, ticker: str) -> List[CorporateEvent]:
        """yfinance에서 배당·주식분할 이벤트를 수집한다.

        Returns:
            전체 히스토리 기반 CorporateEvent 리스트 (날짜 오름차순)
        """
        pass
