import asyncio
import logging
from typing import List

import yfinance as yf

from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.dashboard.domain.exception.stock_exception import (
    InvalidTickerException,
    StockDataFetchException,
)

logger = logging.getLogger(__name__)

_INDEX_TICKER_MAP = {
    "IXIC": "^IXIC",
    "DJI": "^DJI",
    "INDU": "^DJI",
    "GSPC": "^GSPC",
    "SPX": "^GSPC",
    "RUT": "^RUT",
    "VIX": "^VIX",
    "FTSE": "^FTSE",
    "N225": "^N225",
    "HSI": "^HSI",
    "GDAXI": "^GDAXI",
    "KS11": "^KS11",
    "KQ11": "^KQ11",
    "KS200": "^KS200",
    "SSEC": "000001.SS",
    "TNX": "^TNX",
}


def _to_yfinance_ticker(ticker: str) -> str:
    if ticker.startswith("^"):
        return ticker
    return _INDEX_TICKER_MAP.get(ticker, ticker)


class YahooFinanceStockClient(StockBarsPort):

    async def fetch_stock_bars(self, ticker: str, period: str) -> tuple[str, List[StockBar]]:
        try:
            loop = asyncio.get_event_loop()
            company_name, df = await loop.run_in_executor(None, self._fetch_sync, ticker, period)
            return company_name, self._to_entities(df, ticker, period)
        except (InvalidTickerException, StockDataFetchException):
            raise
        except Exception as e:
            logger.error("[YahooFinanceStock] 예상치 못한 오류 (ticker=%s): %s", ticker, e)
            raise StockDataFetchException(f"yfinance 호출 중 오류가 발생했습니다: {e}")

    def _fetch_sync(self, ticker: str, period: str) -> tuple[str, object]:
        logger.info("[YahooFinanceStock] %s 데이터 수집 시작 (period=%s)", ticker, period)
        yf_ticker = _to_yfinance_ticker(ticker)
        t = yf.Ticker(yf_ticker)
        df = t.history(period=period, interval="1d")
        if df is None or df.empty:
            raise InvalidTickerException(ticker)
        info = t.info
        company_name = info.get("longName") or info.get("shortName") or ticker
        return company_name, df

    @staticmethod
    def _to_entities(df, ticker: str, period: str) -> List[StockBar]:
        bars: List[StockBar] = []
        for ts, row in df.iterrows():
            try:
                bar_date = ts.date() if hasattr(ts, "date") else ts
                bars.append(
                    StockBar(
                        ticker=ticker,
                        bar_date=bar_date,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume", 0) or 0),
                    )
                )
            except Exception as e:
                logger.warning("[YahooFinanceStock] 행 변환 실패 (ts=%s): %s", ts, e)

        if not bars:
            raise StockDataFetchException(
                f"유효한 OHLCV 행이 없습니다. ticker={ticker}, period={period}"
            )

        logger.info("[YahooFinanceStock] %s 수집 완료: %d bars (period=%s)", ticker, len(bars), period)
        return bars
