import logging
from functools import partial

import yfinance as yf

from app.domains.dashboard.adapter.outbound.external._yfinance_retry import (
    yfinance_call_with_retry,
)
from app.domains.dashboard.application.port.out.asset_type_port import AssetTypePort
from app.infrastructure.external.yahoo_ticker import normalize_yfinance_ticker

logger = logging.getLogger(__name__)


class YahooFinanceAssetTypeClient(AssetTypePort):

    async def get_quote_type(self, ticker: str) -> str:
        try:
            return await yfinance_call_with_retry(
                partial(self._fetch_sync, ticker),
                logger_prefix=f"YahooFinanceAssetType:{ticker}",
            )
        except Exception as e:
            logger.warning("[YahooFinanceAssetType] quoteType 조회 실패 (ticker=%s): %s", ticker, e)
            return "UNKNOWN"

    @staticmethod
    def _fetch_sync(ticker: str) -> str:
        yf_ticker = normalize_yfinance_ticker(ticker)
        info = yf.Ticker(yf_ticker).info or {}
        quote_type = info.get("quoteType") or "UNKNOWN"
        logger.info("[YahooFinanceAssetType] %s quoteType=%s", ticker, quote_type)
        return str(quote_type).upper()
