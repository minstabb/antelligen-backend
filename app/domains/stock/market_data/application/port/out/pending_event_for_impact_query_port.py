from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List


@dataclass(frozen=True)
class PendingEventForImpact:
    """AR 미계산 이벤트 식별자.

    event_enrichments 행 중 event_impact_metrics 에 (ticker, event_date, event_type,
    detail_hash) 매칭이 없거나 일부 윈도우만 계산된 행을 가리킨다.
    """

    ticker: str
    event_date: date
    event_type: str
    detail_hash: str


class PendingEventForImpactQueryPort(ABC):
    """AR 계산 대상 이벤트 read-side 쿼리 포트.

    구현은 event_enrichments × event_impact_metrics LEFT JOIN. cross-domain ORM
    참조를 격리하기 위해 read-side 만 분리.
    """

    @abstractmethod
    async def find_pending(
        self,
        cutoff_date: date,
        event_types: List[str],
        limit: int = 1000,
    ) -> List[PendingEventForImpact]:
        ...
