from abc import ABC, abstractmethod
from typing import List, Optional

from app.domains.schedule.domain.entity.event_impact_analysis import EventImpactAnalysis


class EventImpactAnalysisRepositoryPort(ABC):
    @abstractmethod
    async def upsert(self, analysis: EventImpactAnalysis) -> EventImpactAnalysis:
        """event_id 기준으로 기존 분석이 있으면 갱신, 없으면 신규 저장."""
        ...

    @abstractmethod
    async def find_by_event_id(self, event_id: int) -> Optional[EventImpactAnalysis]:
        ...

    @abstractmethod
    async def find_by_event_ids(self, event_ids: List[int]) -> List[EventImpactAnalysis]:
        ...
