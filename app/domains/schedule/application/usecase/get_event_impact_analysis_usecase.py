from datetime import date
from typing import Dict, List, Optional

from app.domains.schedule.application.port.out.economic_event_repository_port import (
    EconomicEventRepositoryPort,
)
from app.domains.schedule.application.port.out.event_impact_analysis_repository_port import (
    EventImpactAnalysisRepositoryPort,
)
from app.domains.schedule.application.response.event_impact_analysis_response import (
    EventImpactAnalysisItem,
    ListEventAnalysisResponse,
)
from app.domains.schedule.application.usecase.run_event_impact_analysis_usecase import (
    annotate_duplicate_titles,
)


class GetEventImpactAnalysisUseCase:
    def __init__(
        self,
        event_repository: EconomicEventRepositoryPort,
        analysis_repository: EventImpactAnalysisRepositoryPort,
    ):
        self._event_repository = event_repository
        self._analysis_repository = analysis_repository

    async def execute(
        self,
        year: Optional[int] = None,
        country: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> ListEventAnalysisResponse:
        base_year = year or date.today().year
        start = date(base_year, 1, 1)
        end = date(base_year, 12, 31)

        events = await self._event_repository.find_by_range(
            start=start,
            end=end,
            country=country,
            importance=importance,
        )
        event_ids = [e.id for e in events if e.id is not None]
        analyses = await self._analysis_repository.find_by_event_ids(event_ids)
        by_event: Dict[int, object] = {a.event_id: a for a in analyses}

        items: List[EventImpactAnalysisItem] = []
        for event in events:
            analysis = by_event.get(event.id)
            if analysis is None:
                continue
            items.append(
                EventImpactAnalysisItem(
                    id=analysis.id,
                    event_id=analysis.event_id,
                    event_title=event.title,
                    event_country=event.country,
                    event_at=event.event_at,
                    event_importance=event.importance.value,
                    summary=analysis.summary,
                    direction=analysis.direction,
                    impact_tags=list(analysis.impact_tags),
                    key_drivers=list(analysis.key_drivers),
                    risks=list(analysis.risks),
                    indicator_snapshot=dict(analysis.indicator_snapshot),
                    model_name=analysis.model_name,
                    generated_at=analysis.generated_at,
                    updated_at=analysis.updated_at,
                )
            )

        items.sort(key=lambda it: it.event_at)
        annotate_duplicate_titles(items, "event_title", "event_country")
        return ListEventAnalysisResponse(items=items)
