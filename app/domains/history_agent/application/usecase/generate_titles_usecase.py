import logging
import time
from typing import Dict, List, Tuple

from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.application.request.title_request import (
    TitleBatchRequest,
    TitleEventRequest,
)
from app.domains.history_agent.application.response.title_response import (
    TitleBatchResponse,
    TitleItem,
)
from app.domains.history_agent.application.service.title_generation_service import (
    OTHER_TITLE_SYSTEM,
    batch_titles,
)
from app.domains.history_agent.domain.entity.event_enrichment import (
    EventEnrichment,
    compute_detail_hash,
)

logger = logging.getLogger(__name__)


def _build_line(event: TitleEventRequest) -> str:
    return f"type={event.type} detail={event.detail}"


class GenerateTitlesUseCase:

    def __init__(self, enrichment_repo: EventEnrichmentRepositoryPort):
        self._enrichment_repo = enrichment_repo

    async def execute(self, request: TitleBatchRequest) -> TitleBatchResponse:
        start = time.monotonic()
        ticker = request.ticker.upper()
        events = request.events

        if not events:
            return TitleBatchResponse(titles=[])

        hashes = [compute_detail_hash(e.detail) for e in events]
        keys: List[Tuple[str, ...]] = [
            (ticker, e.date, e.type, h) for e, h in zip(events, hashes)
        ]

        db_hits = await self._enrichment_repo.find_by_keys(keys)
        db_map: Dict[Tuple, EventEnrichment] = {
            (r.ticker, r.event_date, r.event_type, r.detail_hash): r for r in db_hits
        }

        miss_events: List[TitleEventRequest] = []
        miss_indices: List[int] = []
        titles: List[str] = [""] * len(events)

        for idx, (event, h) in enumerate(zip(events, hashes)):
            cached = db_map.get((ticker, event.date, event.type, h))
            if cached:
                titles[idx] = cached.title
            else:
                miss_events.append(event)
                miss_indices.append(idx)

        db_hit_count = len(events) - len(miss_events)

        if miss_events:
            generated = await batch_titles(miss_events, OTHER_TITLE_SYSTEM, _build_line)
            new_enrichments: List[EventEnrichment] = []
            for idx_in_miss, (event, title) in enumerate(zip(miss_events, generated)):
                original_idx = miss_indices[idx_in_miss]
                titles[original_idx] = title
                new_enrichments.append(
                    EventEnrichment(
                        ticker=ticker,
                        event_date=event.date,
                        event_type=event.type,
                        detail_hash=hashes[original_idx],
                        title=title,
                    )
                )
            await self._enrichment_repo.upsert_bulk(new_enrichments)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "[GenerateTitles] titles endpoint: req=%d db_hit=%d llm=%d elapsed=%dms ticker=%s",
            len(events), db_hit_count, len(miss_events), elapsed_ms, ticker,
        )

        items = [
            TitleItem(
                date=event.date,
                type=event.type,
                detail_hash=hashes[idx],
                title=titles[idx],
            )
            for idx, event in enumerate(events)
        ]
        return TitleBatchResponse(titles=items)
