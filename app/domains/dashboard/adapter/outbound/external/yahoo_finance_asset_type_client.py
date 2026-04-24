import asyncio
import logging

import yfinance as yf

from app.domains.dashboard.application.port.out.asset_type_port import AssetTypePort

logger = logging.getLogger(__name__)


class YahooFinanceAssetTypeClient(AssetTypePort):

    async def get_quote_type(self, ticker: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._fetch_sync, ticker)
        except Exception as e:
            logger.warning("[YahooFinanceAssetType] quoteType 조회 실패 (ticker=%s): %s", ticker, e)
            return "UNKNOWN"

    @staticmethod
    def _fetch_sync(ticker: str) -> str:
        info = yf.Ticker(ticker).info or {}
        quote_type = info.get("quoteType") or "UNKNOWN"
        logger.info("[YahooFinanceAssetType] %s quoteType=%s", ticker, quote_type)
        return str(quote_type).upper()
