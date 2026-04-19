import asyncio
import logging

from app.domains.dashboard.application.port.out.fred_macro_port import FredMacroPort
from app.domains.dashboard.application.response.macro_data_response import (
    MacroDataPointResponse,
    MacroDataResponse,
)

logger = logging.getLogger(__name__)

_PERIOD_TO_MONTHS: dict[str, int] = {
    "1D": 1,
    "1W": 3,
    "1M": 6,
    "1Y": 24,
}

FEDFUNDS = "FEDFUNDS"
CPIAUCSL = "CPIAUCSL"
UNRATE = "UNRATE"


class GetMacroDataUseCase:

    def __init__(self, fred_macro_port: FredMacroPort):
        self._fred = fred_macro_port

    async def execute(self, period: str) -> MacroDataResponse:
        """3종 거시경제 지표를 병렬로 조회한다.

        Args:
            period: "1D" | "1W" | "1M" | "1Y"

        Returns:
            MacroDataResponse (interestRate, cpi, unemployment)
        """
        months = _PERIOD_TO_MONTHS[period]

        interest_rate_data, cpi_data, unemployment_data = await asyncio.gather(
            self._fred.fetch_series(FEDFUNDS, months),
            self._fred.fetch_series(CPIAUCSL, months),
            self._fred.fetch_series(UNRATE, months),
        )

        logger.info(
            "[GetMacroData] 완료: period=%s, interestRate=%d, cpi=%d, unemployment=%d",
            period,
            len(interest_rate_data),
            len(cpi_data),
            len(unemployment_data),
        )

        return MacroDataResponse(
            period=period,
            interestRate=[MacroDataPointResponse.from_entity(p) for p in interest_rate_data],
            cpi=[MacroDataPointResponse.from_entity(p) for p in cpi_data],
            unemployment=[MacroDataPointResponse.from_entity(p) for p in unemployment_data],
        )
