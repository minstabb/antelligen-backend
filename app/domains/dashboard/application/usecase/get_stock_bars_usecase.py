import logging
from datetime import date, timedelta
from typing import Callable, List, Optional

import redis.asyncio as aioredis

from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.application.response.stock_bar_response import (
    StockBarResponse,
    StockBarsResponse,
)
from app.domains.dashboard.domain.entity.stock_bar import StockBar

logger = logging.getLogger(__name__)

_PERIOD_TO_YFINANCE: dict[str, str] = {
    "1D": "max",
    "1W": "max",
    "1M": "max",
    "1Y": "max",
}

_PERIOD_CONFIG: dict[str, dict] = {
    "1D": {"key_fn": None},
    "1W": {"key_fn": "week"},
    "1M": {"key_fn": "month"},
    "1Y": {"key_fn": "year"},
}

_CACHE_TTL = 3600


def _week_key(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month_key(d: date) -> date:
    return date(d.year, d.month, 1)


def _year_key(d: date) -> date:
    return date(d.year, 1, 1)


_KEY_FN_MAP: dict[str, Callable[[date], date]] = {
    "week": _week_key,
    "month": _month_key,
    "year": _year_key,
}


def _aggregate(daily_bars: List[StockBar], key_fn: Callable[[date], date]) -> List[StockBar]:
    groups: dict[date, List[StockBar]] = {}
    for bar in daily_bars:
        key = key_fn(bar.bar_date)
        groups.setdefault(key, []).append(bar)

    aggregated: List[StockBar] = []
    for key in sorted(groups):
        group = groups[key]
        aggregated.append(
            StockBar(
                ticker=group[0].ticker,
                bar_date=key,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )
    return aggregated


class GetStockBarsUseCase:

    def __init__(self, stock_bars_port: StockBarsPort, redis: aioredis.Redis):
        self._stock_bars_port = stock_bars_port
        self._redis = redis

    async def execute(self, ticker: str, period: str) -> StockBarsResponse:
        cache_key = f"stock_bars:{ticker}:{period}"

        cached = await self._redis.get(cache_key)
        if cached:
            try:
                logger.info("[GetStockBars] 캐시 히트: ticker=%s, period=%s", ticker, period)
                return StockBarsResponse.model_validate_json(cached)
            except Exception:
                pass  # 캐시 스키마 불일치 시 재조회

        yfinance_period = _PERIOD_TO_YFINANCE[period]
        company_name, daily_bars = await self._stock_bars_port.fetch_stock_bars(ticker, yfinance_period)

        key_fn_name: Optional[str] = _PERIOD_CONFIG[period]["key_fn"]

        if key_fn_name is None:
            bars = daily_bars
        else:
            bars = _aggregate(daily_bars, _KEY_FN_MAP[key_fn_name])

        response = StockBarsResponse(
            ticker=ticker,
            company_name=company_name,
            period=period,
            count=len(bars),
            bars=[StockBarResponse.from_entity(bar) for bar in bars],
        )

        await self._redis.setex(cache_key, _CACHE_TTL, response.model_dump_json())
        logger.info(
            "[GetStockBars] 완료: ticker=%s, period=%s, returned=%d",
            ticker, period, len(bars),
        )

        return response
