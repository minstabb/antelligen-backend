import logging
from datetime import date, timedelta
from typing import List

from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.application.response.price_event_response import (
    PriceEventResponse,
    PriceEventsResponse,
)
from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.dashboard.domain.service.price_event_collector import PriceEventCollector

logger = logging.getLogger(__name__)

_PERIOD_TO_DAYS: dict[str, int] = {
    "1D": 365,
    "1W": 365 * 3,
    "1M": 365 * 5,
    "1Y": 365 * 20,
}


class GetPriceEventsUseCase:

    def __init__(self, stock_bars_port: StockBarsPort):
        self._stock_bars_port = stock_bars_port
        self._collector = PriceEventCollector()

    async def execute(self, ticker: str, period: str) -> PriceEventsResponse:
        # 52주 감지 윈도우(252일) 확보를 위해 요청 기간보다 1년 더 fetch
        _, all_bars = await self._stock_bars_port.fetch_stock_bars(ticker, "max")

        days = _PERIOD_TO_DAYS[period]
        start_date = date.today() - timedelta(days=days)

        all_events = self._collector.collect(all_bars)
        filtered = [e for e in all_events if e.date >= start_date]

        logger.info(
            "[GetPriceEvents] ticker=%s, period=%s, total=%d, filtered=%d",
            ticker, period, len(all_events), len(filtered),
        )

        return PriceEventsResponse(
            ticker=ticker,
            period=period,
            count=len(filtered),
            events=[PriceEventResponse.from_entity(e) for e in filtered],
        )
