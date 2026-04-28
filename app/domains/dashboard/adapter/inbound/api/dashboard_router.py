import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.app_exception import AppException
from app.common.response.base_response import BaseResponse
from app.domains.dashboard.adapter.outbound.external.fred_macro_client import FredMacroClient
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_nasdaq_client import (
    YahooFinanceNasdaqClient,
)
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_stock_client import (
    YahooFinanceStockClient,
)
from app.domains.dashboard.adapter.outbound.persistence.nasdaq_repository_impl import (
    NasdaqRepositoryImpl,
)
from app.domains.dashboard.application.response.economic_event_response import EconomicEventsResponse
from app.domains.dashboard.application.response.macro_data_response import MacroDataResponse
from app.domains.dashboard.application.response.nasdaq_bar_response import NasdaqBarsResponse
from app.domains.dashboard.application.response.stock_bar_response import StockBarsResponse
from app.domains.dashboard.application.usecase.collect_nasdaq_bars_usecase import (
    CollectNasdaqBarsUseCase,
)
from app.domains.dashboard.application.usecase.get_economic_events_usecase import (
    GetEconomicEventsUseCase,
)
from app.domains.dashboard.application.usecase.get_macro_data_usecase import GetMacroDataUseCase
from app.domains.dashboard.application.usecase.get_nasdaq_bars_usecase import (
    GetNasdaqBarsUseCase,
)
from app.domains.dashboard.application.usecase.get_stock_bars_usecase import GetStockBarsUseCase
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.database.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_VALID_PERIODS = {"1D", "1W", "1M", "1Y"}


def _validate_chart_interval(chart_interval: str) -> str:
    """ADR-0001: chart_interval 만 허용. `period` deprecation 완료 (Phase 3)."""
    if chart_interval not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 chart_interval입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )
    return chart_interval


@router.get("/nasdaq", response_model=BaseResponse[NasdaqBarsResponse])
async def get_nasdaq_bars(
    chart_interval: str = Query("1M", alias="chartInterval", description="봉 단위: 1D | 1W | 1M | 1Y"),
    db: AsyncSession = Depends(get_db),
):
    """나스닥(^IXIC) OHLCV 일봉 데이터를 반환합니다."""
    effective = _validate_chart_interval(chart_interval)

    result = await GetNasdaqBarsUseCase(
        nasdaq_repository=NasdaqRepositoryImpl(db),
    ).execute(period=effective)

    return BaseResponse.ok(data=result)


@router.get("/macro", response_model=BaseResponse[MacroDataResponse])
async def get_macro_data(
    chart_interval: str = Query("1M", alias="chartInterval", description="봉 단위: 1D | 1W | 1M | 1Y"),
):
    """거시경제 지표(기준금리·CPI·실업률)를 FRED API에서 실시간 조회합니다."""
    effective = _validate_chart_interval(chart_interval)

    result = await GetMacroDataUseCase(
        fred_macro_port=FredMacroClient(),
    ).execute(period=effective)

    return BaseResponse.ok(data=result)


@router.get("/economic-events", response_model=BaseResponse[EconomicEventsResponse])
async def get_economic_events(
    chart_interval: str = Query("1M", alias="chartInterval", description="봉 단위: 1D | 1W | 1M | 1Y"),
):
    """경제 이벤트(기준금리·CPI·실업률 발표 이력)를 FRED API에서 실시간 조회합니다.

    chart_interval별 날짜 범위: 1D=365일 / 1W=1,095일 / 1M=1,825일 / 1Y=7,300일
    """
    effective = _validate_chart_interval(chart_interval)

    result = await GetEconomicEventsUseCase(
        fred_macro_port=FredMacroClient(),
    ).execute(period=effective)

    return BaseResponse.ok(data=result)


@router.get("/stocks/{ticker}/bars", response_model=BaseResponse[StockBarsResponse])
async def get_stock_bars(
    ticker: str,
    chart_interval: str = Query("1D", alias="chartInterval", description="봉 단위: 1D | 1W | 1M | 1Y"),
    redis: aioredis.Redis = Depends(get_redis),
):
    """개별 종목 OHLCV 시계열 데이터를 반환합니다. (yfinance + Redis 캐시)"""
    effective = _validate_chart_interval(chart_interval)

    result = await GetStockBarsUseCase(
        stock_bars_port=YahooFinanceStockClient(),
        redis=redis,
    ).execute(ticker=ticker.upper(), period=effective)

    return BaseResponse.ok(data=result)


# §13.4 C: /price-events 엔드포인트 철거.
# PRICE 카테고리(LOW_52W/HIGH_52W/SURGE/PLUNGE/GAP)는 `/history-agent/anomaly-bars`
# 엔드포인트가 차트 이상치 봉 마커로 대체.


@router.post("/nasdaq/collect", response_model=BaseResponse[dict])
async def collect_nasdaq_bars(
    period: str = Query("5d", description="yfinance period (예: 5d, 1mo, 1y)"),
    db: AsyncSession = Depends(get_db),
):
    """나스닥 일봉 데이터를 yfinance에서 즉시 수집합니다. (수동 트리거용)"""
    saved = await CollectNasdaqBarsUseCase(
        yahoo_finance_port=YahooFinanceNasdaqClient(),
        nasdaq_repository=NasdaqRepositoryImpl(db),
    ).execute(period=period)

    return BaseResponse.ok(data={"saved": saved, "period": period})
