from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional, Set, Tuple

from app.domains.schedule.domain.entity.economic_event import EconomicEvent


class EconomicEventRepositoryPort(ABC):
    @abstractmethod
    async def existing_source_ids(
        self, source: str, source_event_ids: List[str]
    ) -> Set[str]:
        """주어진 source_event_id 중 이미 저장된 것들의 집합을 반환."""
        ...

    @abstractmethod
    async def save_all(self, events: List[EconomicEvent]) -> int:
        """신규 이벤트를 저장하고 저장된 건수를 반환한다."""
        ...

    @abstractmethod
    async def delete_by_source(self, source: str) -> int:
        """해당 source 의 모든 이벤트를 삭제하고 삭제 건수를 반환한다."""
        ...

    @abstractmethod
    async def find_by_range(
        self,
        start: date,
        end: date,
        country: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> List[EconomicEvent]:
        ...
