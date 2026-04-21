from abc import ABC, abstractmethod

from app.domains.disclosure.domain.entity.foreign_filing import ForeignFiling


class ForeignDisclosureApiPort(ABC):
    """해외(US) 공시 조회 포트 (SEC EDGAR 등)"""

    @abstractmethod
    async def fetch_recent_filings(
        self,
        ticker: str,
        form_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[ForeignFiling]:
        pass
