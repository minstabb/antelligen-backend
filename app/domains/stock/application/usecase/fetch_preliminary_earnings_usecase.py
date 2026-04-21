from typing import Optional

from app.domains.stock.application.port.corp_code_repository import CorpCodeRepository
from app.domains.stock.application.port.preliminary_earnings_port import PreliminaryEarningsPort
from app.domains.stock.domain.value_object.earnings_release import EarningsRelease


class FetchPreliminaryEarningsUseCase:
    """종목코드 → corp_code → DART 잠정실적 조회"""

    def __init__(
        self,
        corp_code_repository: CorpCodeRepository,
        preliminary_earnings_port: PreliminaryEarningsPort,
    ) -> None:
        self._corp_repo = corp_code_repository
        self._port = preliminary_earnings_port

    async def execute(self, ticker: str, within_days: int = 120) -> Optional[EarningsRelease]:
        mapping = await self._corp_repo.find_by_ticker(ticker)
        if mapping is None:
            return None

        result = await self._port.fetch_latest_preliminary(
            corp_code=mapping.corp_code,
            within_days=within_days,
        )
        if result:
            result.ticker = ticker  # fill in ticker that provider left blank
        return result
