import logging

import redis.asyncio as aioredis

from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.application.response.stock_bar_response import (
    StockBarResponse,
    StockBarsResponse,
)
from app.domains.dashboard.domain.entity.stock_bar import StockBar  # noqa: F401

logger = logging.getLogger(__name__)

# §17 / ADR-0001: period(UI 값) → chart_interval(봉 단위) 정규화.
# 레거시 "1Y"는 내부 "1Q"(분기봉)로 매핑 (yfinance 연봉 미지원).
_CHART_INTERVAL_ALIAS: dict[str, str] = {"1Y": "1Q"}
_VALID_CHART_INTERVALS = {"1D", "1W", "1M", "1Q"}

_CACHE_TTL = 3600
# 캐시 키 버전: 이전 daily-aggregate 방식 응답과 키 공유 방지 (§17 F).
_CACHE_VERSION = "v2"


class GetStockBarsUseCase:

    def __init__(self, stock_bars_port: StockBarsPort, redis: aioredis.Redis):
        self._stock_bars_port = stock_bars_port
        self._redis = redis

    async def execute(self, ticker: str, period: str) -> StockBarsResponse:
        chart_interval = _CHART_INTERVAL_ALIAS.get(period, period)
        if chart_interval not in _VALID_CHART_INTERVALS:
            raise ValueError(
                f"Unsupported period: {period!r}. Expected one of {sorted(_VALID_CHART_INTERVALS)} or '1Y'."
            )

        cache_key = f"stock_bars:{_CACHE_VERSION}:{ticker}:{chart_interval}"

        cached = await self._redis.get(cache_key)
        if cached:
            try:
                logger.info(
                    "[GetStockBars] 캐시 히트: ticker=%s, chart_interval=%s", ticker, chart_interval,
                )
                return StockBarsResponse.model_validate_json(cached)
            except Exception:
                pass  # 캐시 스키마 불일치 시 재조회

        company_name, bars = await self._stock_bars_port.fetch_stock_bars(
            ticker, chart_interval
        )

        response = StockBarsResponse(
            ticker=ticker,
            company_name=company_name,
            chart_interval=chart_interval,
            count=len(bars),
            bars=[StockBarResponse.from_entity(bar) for bar in bars],
        )

        await self._redis.setex(cache_key, _CACHE_TTL, response.model_dump_json())
        logger.info(
            "[GetStockBars] 완료: ticker=%s, chart_interval=%s, returned=%d",
            ticker, chart_interval, len(bars),
        )

        return response
