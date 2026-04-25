from abc import ABC, abstractmethod
from typing import Optional


class UsCompanyNamePort(ABC):
    """미국 종목 ticker → 정식 회사명 lookup."""

    @abstractmethod
    async def resolve_company_name(self, ticker: str) -> Optional[str]:
        pass
