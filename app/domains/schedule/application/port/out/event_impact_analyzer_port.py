from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List

from app.domains.schedule.domain.entity.economic_event import EconomicEvent


@dataclass
class EventImpactAnalysisResult:
    summary: str
    direction: str  # bullish / bearish / neutral / mixed
    impact_tags: List[str]
    key_drivers: List[str]
    risks: List[str]


class EventImpactAnalyzerPort(ABC):
    @abstractmethod
    async def analyze(
        self,
        event: EconomicEvent,
        indicator_snapshot: Dict[str, Any],
    ) -> EventImpactAnalysisResult:
        """경제 일정과 매크로 지표 스냅샷을 받아 구조화된 영향 분석 결과를 반환."""
        ...
