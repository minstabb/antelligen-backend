import logging

from app.domains.dashboard.application.port.out.nasdaq_repository_port import NasdaqRepositoryPort
from app.domains.dashboard.application.port.out.yahoo_finance_port import YahooFinancePort

logger = logging.getLogger(__name__)


class CollectNasdaqBarsUseCase:

    def __init__(
        self,
        yahoo_finance_port: YahooFinancePort,
        nasdaq_repository: NasdaqRepositoryPort,
    ):
        self._yahoo_finance = yahoo_finance_port
        self._nasdaq_repository = nasdaq_repository

    async def execute(self, period: str = "5d") -> int:
        """yfinance에서 나스닥 일봉 데이터를 수집해 DB에 upsert한다.

        Args:
            period: yfinance period 문자열 (기본값: "5d" — 최근 5 영업일)

        Returns:
            upsert된 행 수
        """
        bars = await self._yahoo_finance.fetch_nasdaq_bars(period=period)
        saved = await self._nasdaq_repository.upsert_bulk(bars)
        logger.info(
            "[CollectNasdaqBars] 완료: fetched=%d, saved=%d (period=%s)",
            len(bars),
            saved,
            period,
        )
        return saved
