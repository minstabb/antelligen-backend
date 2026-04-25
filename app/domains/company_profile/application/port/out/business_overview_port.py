from abc import ABC, abstractmethod
from typing import Optional

from app.domains.company_profile.domain.value_object.business_overview import BusinessOverview


class BusinessOverviewPort(ABC):
    @abstractmethod
    async def generate(
        self,
        corp_name: str,
        induty_code: Optional[str],
        rag_context: Optional[str],
    ) -> Optional[BusinessOverview]:
        pass
