from abc import ABC, abstractmethod
from datetime import date
from typing import List, Tuple

from app.domains.history_agent.domain.entity.event_enrichment import EventEnrichment


class EventEnrichmentRepositoryPort(ABC):

    @abstractmethod
    async def find_by_keys(
        self, keys: List[Tuple[str, date, str, str]]
    ) -> List[EventEnrichment]:
        """(ticker, event_date, event_type, detail_hash) 키 목록으로 배치 조회한다."""
        pass

    @abstractmethod
    async def upsert_bulk(self, enrichments: List[EventEnrichment]) -> int:
        """enrichment 결과를 upsert한다. 저장된 건수를 반환한다."""
        pass
