from abc import ABC, abstractmethod
from datetime import date
from typing import List

from app.domains.schedule.domain.entity.economic_event import EconomicEvent


class EconomicEventFetchPort(ABC):
    @abstractmethod
    async def fetch(self, start: date, end: date) -> List[EconomicEvent]:
        """지정된 기간(포함)의 주요 경제 일정을 외부 소스에서 조회한다."""
        ...
