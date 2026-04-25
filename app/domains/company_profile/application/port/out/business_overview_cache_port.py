from abc import ABC, abstractmethod
from typing import Optional

from app.domains.company_profile.domain.value_object.business_overview import BusinessOverview


class BusinessOverviewCachePort(ABC):
    @abstractmethod
    async def get(self, corp_code: str) -> Optional[BusinessOverview]:
        pass

    @abstractmethod
    async def save(self, corp_code: str, overview: BusinessOverview, ttl_seconds: int) -> None:
        pass
