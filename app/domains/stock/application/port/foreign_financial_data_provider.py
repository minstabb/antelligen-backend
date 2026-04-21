from abc import ABC, abstractmethod
from typing import Optional

from app.domains.stock.domain.entity.financial_ratio import FinancialRatio
from app.domains.stock.domain.value_object.earnings_release import EarningsRelease


class ForeignFinancialDataProvider(ABC):
    """해외(US) 종목 재무 데이터 포트"""

    @abstractmethod
    async def fetch_financial_ratios(self, ticker: str) -> Optional[FinancialRatio]:
        pass

    @abstractmethod
    async def fetch_recent_earnings(self, ticker: str) -> Optional[EarningsRelease]:
        pass
