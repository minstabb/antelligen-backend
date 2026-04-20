import asyncio
import logging
from typing import List

import yfinance as yf

from app.domains.dashboard.application.port.out.yahoo_finance_port import YahooFinancePort
from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar
from app.domains.dashboard.domain.exception.nasdaq_exception import NasdaqDataFetchException

logger = logging.getLogger(__name__)

NASDAQ_TICKER = "^IXIC"


class YahooFinanceNasdaqClient(YahooFinancePort):

    async def fetch_nasdaq_bars(self, period: str) -> List[NasdaqBar]:
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, self._fetch_sync, period)
            return self._to_entities(df, period)
        except NasdaqDataFetchException:
            raise
        except Exception as e:
            logger.error("[YahooFinance] 예상치 못한 오류: %s", e)
            raise NasdaqDataFetchException(f"yfinance 호출 중 오류가 발생했습니다: {e}")

    def _fetch_sync(self, period: str):
        logger.info("[YahooFinance] ^IXIC 데이터 수집 시작 (period=%s)", period)
        ticker = yf.Ticker(NASDAQ_TICKER)
        df = ticker.history(period=period, interval="1d")
        if df is None or df.empty:
            raise NasdaqDataFetchException(
                f"yfinance가 빈 데이터를 반환했습니다. ticker={NASDAQ_TICKER}, period={period}"
            )
        return df

    @staticmethod
    def _to_entities(df, period: str) -> List[NasdaqBar]:
        bars: List[NasdaqBar] = []
        for ts, row in df.iterrows():
            try:
                bar_date = ts.date() if hasattr(ts, "date") else ts
                bars.append(
                    NasdaqBar(
                        bar_date=bar_date,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume", 0) or 0),
                    )
                )
            except Exception as e:
                logger.warning("[YahooFinance] 행 변환 실패 (ts=%s): %s", ts, e)

        if not bars:
            raise NasdaqDataFetchException(
                f"유효한 OHLCV 행이 없습니다. ticker={NASDAQ_TICKER}, period={period}"
            )

        logger.info("[YahooFinance] ^IXIC 수집 완료: %d bars (period=%s)", len(bars), period)
        return bars
