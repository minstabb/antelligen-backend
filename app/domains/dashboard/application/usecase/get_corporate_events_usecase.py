import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Optional

from app.domains.dashboard.adapter.outbound.external.dart_corporate_event_client import (
    DartCorporateEventClient,
)
from app.domains.dashboard.application.port.out.yfinance_corporate_event_port import (
    YahooFinanceCorporateEventPort,
)
from app.domains.dashboard.application.response.corporate_event_response import (
    CorporateEventResponse,
    CorporateEventsResponse,
)
from app.domains.dashboard.domain.service.corporate_event_collector import CorporateEventCollector

logger = logging.getLogger(__name__)

_PERIOD_TO_DAYS: dict[str, int] = {
    "1D": 365,
    "1W": 365 * 3,
    "1M": 365 * 5,
    "1Q": 365 * 20,
    "1Y": 365 * 20,
}

_KOREAN_TICKER_RE = re.compile(r"^\d{6}$")


def _is_korean_ticker(ticker: str) -> bool:
    return bool(_KOREAN_TICKER_RE.match(ticker))


class GetCorporateEventsUseCase:

    def __init__(
        self,
        yfinance_port: YahooFinanceCorporateEventPort,
        dart_client: DartCorporateEventClient,
    ):
        self._yfinance_port = yfinance_port
        self._dart_client = dart_client
        self._collector = CorporateEventCollector()

    async def execute(
        self,
        ticker: str,
        period: str,
        corp_code: Optional[str] = None,
    ) -> CorporateEventsResponse:
        days = _PERIOD_TO_DAYS[period]
        start_date = date.today() - timedelta(days=days)

        # yfinance와 DART를 병렬 조회
        async def _empty():
            return []

        dart_task = (
            self._dart_client.fetch_corporate_events(
                corp_code=corp_code,
                start_date=start_date,
                end_date=date.today(),
            )
            if corp_code and _is_korean_ticker(ticker)
            else _empty()
        )

        yfinance_events, dart_events = await asyncio.gather(
            self._yfinance_port.fetch_corporate_events(ticker),
            dart_task,
        )

        # 날짜 범위 필터링
        yfinance_filtered = [e for e in yfinance_events if e.date >= start_date]

        merged = self._collector.merge(dart_events, yfinance_filtered)

        logger.info(
            "[GetCorporateEvents] ticker=%s, period=%s, dart=%d, yfinance=%d, merged=%d",
            ticker, period, len(dart_events), len(yfinance_filtered), len(merged),
        )

        return CorporateEventsResponse(
            ticker=ticker,
            period=period,
            count=len(merged),
            events=[CorporateEventResponse.from_entity(e) for e in merged],
        )
