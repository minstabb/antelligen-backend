from abc import ABC, abstractmethod
from typing import Optional

from app.domains.stock.domain.value_object.earnings_release import EarningsRelease


class PreliminaryEarningsPort(ABC):
    """잠정실적 공시 조회 포트"""

    @abstractmethod
    async def fetch_latest_preliminary(
        self,
        corp_code: str,
        within_days: int = 120,
    ) -> Optional[EarningsRelease]:
        pass
