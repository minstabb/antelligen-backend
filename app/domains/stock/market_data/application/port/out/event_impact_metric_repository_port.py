from abc import ABC, abstractmethod
from datetime import date
from typing import List, Tuple

from app.domains.stock.market_data.domain.entity.event_impact_metric import (
    EventImpactMetric,
)


# (ticker, event_date, event_type, detail_hash, pre_days, post_days)
EventImpactKey = Tuple[str, date, str, str, int, int]


class EventImpactMetricRepositoryPort(ABC):

    @abstractmethod
    async def upsert_bulk(self, metrics: List[EventImpactMetric]) -> int:
        ...

    @abstractmethod
    async def find_by_event_keys(
        self,
        keys: List[Tuple[str, date, str, str]],
    ) -> List[EventImpactMetric]:
        """(ticker, event_date, event_type, detail_hash) 키 목록으로 모든 윈도우의 metric 조회."""
        ...
