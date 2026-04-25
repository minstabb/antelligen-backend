import logging
from functools import partial
from typing import List

import yfinance as yf

from app.domains.dashboard.adapter.outbound.external._yfinance_retry import (
    yfinance_call_with_retry,
)
from app.domains.dashboard.application.port.out.yfinance_corporate_event_port import (
    YahooFinanceCorporateEventPort,
)
from app.domains.dashboard.domain.entity.corporate_event import CorporateEvent, CorporateEventType
from app.infrastructure.external.yahoo_ticker import normalize_yfinance_ticker

logger = logging.getLogger(__name__)


class YahooFinanceCorporateEventClient(YahooFinanceCorporateEventPort):

    async def fetch_corporate_events(self, ticker: str) -> List[CorporateEvent]:
        try:
            return await yfinance_call_with_retry(
                partial(self._fetch_sync, ticker),
                logger_prefix=f"YahooFinanceCorporateEvent:{ticker}",
            )
        except Exception as e:
            logger.error("[YahooFinanceCorporateEvent] 오류 (ticker=%s): %s", ticker, e)
            return []

    def _fetch_sync(self, ticker: str) -> List[CorporateEvent]:
        logger.info("[YahooFinanceCorporateEvent] %s 이벤트 수집 시작", ticker)
        t = yf.Ticker(normalize_yfinance_ticker(ticker))
        events: List[CorporateEvent] = []

        events.extend(self._parse_dividends(t))
        events.extend(self._parse_splits(t))

        events.sort(key=lambda e: e.date)
        logger.info("[YahooFinanceCorporateEvent] %s 수집 완료: %d건", ticker, len(events))
        return events

    @staticmethod
    def _parse_dividends(t: yf.Ticker) -> List[CorporateEvent]:
        events: List[CorporateEvent] = []
        try:
            divs = t.dividends
            if divs is None or divs.empty:
                return []
            for ts, amount in divs.items():
                bar_date = ts.date() if hasattr(ts, "date") else ts
                events.append(CorporateEvent(
                    date=bar_date,
                    type=CorporateEventType.DIVIDEND,
                    detail=f"배당 ${amount:.4f}/주",
                    source="yfinance",
                ))
        except Exception as e:
            logger.warning("[YahooFinanceCorporateEvent] dividends 파싱 실패: %s", e)
        return events

    @staticmethod
    def _parse_splits(t: yf.Ticker) -> List[CorporateEvent]:
        events: List[CorporateEvent] = []
        try:
            splits = t.splits
            if splits is None or splits.empty:
                return []
            for ts, ratio in splits.items():
                bar_date = ts.date() if hasattr(ts, "date") else ts
                events.append(CorporateEvent(
                    date=bar_date,
                    type=CorporateEventType.STOCK_SPLIT,
                    detail=f"주식분할 {ratio:.1f}:1",
                    source="yfinance",
                ))
        except Exception as e:
            logger.warning("[YahooFinanceCorporateEvent] splits 파싱 실패: %s", e)
        return events
