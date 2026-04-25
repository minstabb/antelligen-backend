import logging
from functools import partial
from typing import List

import yfinance as yf

from app.domains.dashboard.adapter.outbound.external._yfinance_retry import (
    yfinance_call_with_retry,
)
from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.dashboard.domain.exception.stock_exception import (
    InvalidTickerException,
    StockDataFetchException,
)
from app.infrastructure.external.yahoo_ticker import candidate_yfinance_tickers

logger = logging.getLogger(__name__)


# chart_interval → yfinance interval (봉 단위)
# 1Q(분기봉)는 yfinance가 연봉(1y)을 미지원해서 3mo(분기봉)로 대체.
_CHART_INTERVAL_TO_YFINANCE: dict[str, str] = {
    "1D": "1d",
    "1W": "1wk",
    "1M": "1mo",
    "1Q": "3mo",
}

# chart_interval → yfinance period (lookback, 봉 개수가 시각화에 적절한 수준이 되도록)
# 1D: 252봉(~1y 거래일), 1W: 156봉(~3y), 1M: 60봉(~5y), 1Q: 80봉(~20y)
_CHART_INTERVAL_TO_LOOKBACK: dict[str, str] = {
    "1D": "1y",
    "1W": "3y",
    "1M": "5y",
    "1Q": "max",
}

# 레거시 "1Y" 입력을 새 "1Q"로 매핑 (§13.2, §17). 하위 호환 유지.
_LEGACY_INTERVAL_ALIAS: dict[str, str] = {"1Y": "1Q"}


def normalize_chart_interval(chart_interval: str) -> str:
    """레거시 별칭 정규화 — 외부 입력 경계에서 호출."""
    return _LEGACY_INTERVAL_ALIAS.get(chart_interval, chart_interval)


def _resolve_yfinance_params(chart_interval: str) -> tuple[str, str]:
    """chart_interval("1D"/"1W"/"1M"/"1Q") → (yfinance_period, yfinance_interval)."""
    chart_interval = normalize_chart_interval(chart_interval)
    yf_interval = _CHART_INTERVAL_TO_YFINANCE.get(chart_interval)
    yf_period = _CHART_INTERVAL_TO_LOOKBACK.get(chart_interval)
    if yf_interval is None or yf_period is None:
        raise ValueError(
            f"Unsupported chart_interval: {chart_interval!r}. "
            f"Expected one of {list(_CHART_INTERVAL_TO_YFINANCE)}."
        )
    return yf_period, yf_interval


class YahooFinanceStockClient(StockBarsPort):

    async def fetch_stock_bars(
        self, ticker: str, chart_interval: str
    ) -> tuple[str, List[StockBar]]:
        try:
            company_name, df, resolved_ticker = await yfinance_call_with_retry(
                partial(self._fetch_sync, ticker, chart_interval),
                logger_prefix=f"YahooFinanceStock:{ticker}",
            )
            return company_name, self._to_entities(df, resolved_ticker, chart_interval)
        except (InvalidTickerException, StockDataFetchException):
            raise
        except Exception as e:
            logger.error("[YahooFinanceStock] 예상치 못한 오류 (ticker=%s): %s", ticker, e)
            raise StockDataFetchException(f"yfinance 호출 중 오류가 발생했습니다: {e}")

    def _fetch_sync(
        self, ticker: str, chart_interval: str
    ) -> tuple[str, object, str]:
        yf_period, yf_interval = _resolve_yfinance_params(chart_interval)
        logger.info(
            "[YahooFinanceStock] %s 수집 시작 (chart_interval=%s, yf_period=%s, yf_interval=%s)",
            ticker, chart_interval, yf_period, yf_interval,
        )
        candidates = candidate_yfinance_tickers(ticker)
        last_df = None
        for idx, yf_ticker in enumerate(candidates):
            t = yf.Ticker(yf_ticker)
            df = t.history(period=yf_period, interval=yf_interval)
            if df is not None and not df.empty:
                if idx > 0:
                    logger.info(
                        "[YahooFinanceStock] %s: %s 데이터 없음 → %s 폴백 성공",
                        ticker, candidates[0], yf_ticker,
                    )
                info = t.info
                company_name = info.get("longName") or info.get("shortName") or ticker
                return company_name, df, yf_ticker
            last_df = df
        # 모든 후보 실패 (e.g. .KS + .KQ 둘 다 빈 응답)
        raise InvalidTickerException(ticker)

    @staticmethod
    def _to_entities(df, ticker: str, chart_interval: str) -> List[StockBar]:
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
                f"유효한 OHLCV 행이 없습니다. ticker={ticker}, chart_interval={chart_interval}"
            )

        logger.info(
            "[YahooFinanceStock] %s 수집 완료: %d bars (chart_interval=%s)",
            ticker, len(bars), chart_interval,
        )
        return bars
