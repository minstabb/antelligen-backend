import logging
from functools import partial
from typing import List

import yfinance as yf

from app.domains.dashboard.adapter.outbound.external._yfinance_retry import (
    yfinance_call_with_retry,
)
from app.domains.dashboard.application.port.out.etf_holdings_port import (
    EtfHolding,
    EtfHoldingsPort,
)

logger = logging.getLogger(__name__)


class YahooFinanceEtfHoldingsClient(EtfHoldingsPort):
    async def get_top_holdings(self, etf_ticker: str, top_n: int = 5) -> List[EtfHolding]:
        try:
            return await yfinance_call_with_retry(
                partial(self._fetch_sync, etf_ticker, top_n),
                logger_prefix=f"YahooFinanceEtfHoldings:{etf_ticker}",
            )
        except Exception as exc:
            logger.warning(
                "[YahooFinanceEtfHoldings] 보유종목 조회 실패 (ticker=%s): %s",
                etf_ticker, exc,
            )
            return []

    @staticmethod
    def _fetch_sync(etf_ticker: str, top_n: int) -> List[EtfHolding]:
        ticker = yf.Ticker(etf_ticker)
        funds = getattr(ticker, "funds_data", None)
        if funds is None:
            return []
        try:
            df = funds.top_holdings
        except Exception as exc:
            logger.info(
                "[YahooFinanceEtfHoldings] top_holdings 접근 실패 (ticker=%s): %s",
                etf_ticker, exc,
            )
            return []

        if df is None or df.empty:
            return []

        results: List[EtfHolding] = []
        for symbol, row in df.head(top_n).iterrows():
            name = str(row.get("Name", "")) if hasattr(row, "get") else ""
            weight = row.get("Holding Percent") if hasattr(row, "get") else None
            if weight is None:
                continue
            try:
                weight_pct = float(weight) * 100.0  # yfinance는 0~1 스케일
            except (TypeError, ValueError):
                continue
            results.append(EtfHolding(ticker=str(symbol), name=name, weight_pct=weight_pct))
        return results
