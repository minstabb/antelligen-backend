from datetime import date
from typing import Optional

from app.domains.schedule.application.port.out.economic_event_repository_port import (
    EconomicEventRepositoryPort,
)
from app.domains.schedule.application.response.economic_event_response import (
    EconomicEventItem,
    GetEconomicEventsResponse,
)


class GetEconomicEventsUseCase:
    def __init__(self, repository: EconomicEventRepositoryPort):
        self._repository = repository

    async def execute(
        self,
        year: Optional[int] = None,
        country: Optional[str] = None,
        importance: Optional[str] = None,
    ) -> GetEconomicEventsResponse:
        base_year = year or date.today().year
        start = date(base_year, 1, 1)
        end = date(base_year, 12, 31)

        events = await self._repository.find_by_range(
            start=start,
            end=end,
            country=country,
            importance=importance,
        )

        items = [
            EconomicEventItem(
                id=e.id,
                title=e.title,
                country=e.country,
                event_at=e.event_at,
                importance=e.importance.value,
                description=e.description,
                reference_url=e.reference_url,
                source=e.source,
            )
            for e in events
        ]
        return GetEconomicEventsResponse(items=items)
