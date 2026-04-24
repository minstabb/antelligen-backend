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
from app.domains.dashboard.adapter.outbound.external.dart_announcement_client import (
    DartAnnouncementClient,
)
from app.domains.dashboard.adapter.outbound.external.dart_corporate_event_client import (
    DartCorporateEventClient,
)
from app.domains.dashboard.adapter.outbound.external.sec_edgar_announcement_client import (
    SecEdgarAnnouncementClient,
)
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_corporate_event_client import (
    YahooFinanceCorporateEventClient,
)
from app.domains.dashboard.application.response.announcement_response import AnnouncementsResponse
from app.domains.dashboard.application.response.corporate_event_response import CorporateEventsResponse
from app.domains.dashboard.application.response.price_event_response import PriceEventsResponse
from app.domains.dashboard.application.usecase.get_announcements_usecase import GetAnnouncementsUseCase
from app.domains.dashboard.application.usecase.get_corporate_events_usecase import (
    GetCorporateEventsUseCase,
)
from app.domains.dashboard.application.usecase.get_price_events_usecase import GetPriceEventsUseCase
from app.domains.dashboard.application.usecase.get_stock_bars_usecase import GetStockBarsUseCase
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.database.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_VALID_PERIODS = {"1D", "1W", "1M", "1Y"}


@router.get("/nasdaq", response_model=BaseResponse[NasdaqBarsResponse])
async def get_nasdaq_bars(
    period: str = Query("1M", description="조회 기간: 1D | 1W | 1M | 1Y"),
    db: AsyncSession = Depends(get_db),
):
    """나스닥(^IXIC) OHLCV 일봉 데이터를 반환합니다."""
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    result = await GetNasdaqBarsUseCase(
        nasdaq_repository=NasdaqRepositoryImpl(db),
    ).execute(period=period)

    return BaseResponse.ok(data=result)


@router.get("/macro", response_model=BaseResponse[MacroDataResponse])
async def get_macro_data(
    period: str = Query("1M", description="조회 기간: 1D | 1W | 1M | 1Y"),
):
    """거시경제 지표(기준금리·CPI·실업률)를 FRED API에서 실시간 조회합니다."""
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    result = await GetMacroDataUseCase(
        fred_macro_port=FredMacroClient(),
    ).execute(period=period)

    return BaseResponse.ok(data=result)


@router.get("/economic-events", response_model=BaseResponse[EconomicEventsResponse])
async def get_economic_events(
    period: str = Query("1M", description="조회 기간: 1D | 1W | 1M | 1Y"),
):
    """경제 이벤트(기준금리·CPI·실업률 발표 이력)를 FRED API에서 실시간 조회합니다.

    period별 날짜 범위: 1D=365일 / 1W=1,095일 / 1M=1,825일 / 1Y=7,300일
    """
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    result = await GetEconomicEventsUseCase(
        fred_macro_port=FredMacroClient(),
    ).execute(period=period)

    return BaseResponse.ok(data=result)


@router.get("/stocks/{ticker}/bars", response_model=BaseResponse[StockBarsResponse])
async def get_stock_bars(
    ticker: str,
    period: str = Query("1D", description="조회 기간: 1D | 1W | 1M | 1Y"),
    redis: aioredis.Redis = Depends(get_redis),
):
    """개별 종목 OHLCV 시계열 데이터를 반환합니다. (yfinance + Redis 캐시)"""
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    result = await GetStockBarsUseCase(
        stock_bars_port=YahooFinanceStockClient(),
        redis=redis,
    ).execute(ticker=ticker.upper(), period=period)

    return BaseResponse.ok(data=result)


@router.get("/stocks/{ticker}/price-events", response_model=BaseResponse[PriceEventsResponse])
async def get_price_events(
    ticker: str,
    period: str = Query("1Y", description="조회 기간: 1D | 1W | 1M | 1Y"),
):
    """개별 종목의 가격 이벤트(52주 신고가/신저가, 급등락, 거래량 급증, 갭)를 반환합니다."""
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    result = await GetPriceEventsUseCase(
        stock_bars_port=YahooFinanceStockClient(),
    ).execute(ticker=ticker.upper(), period=period)

    return BaseResponse.ok(data=result)


@router.get("/stocks/{ticker}/corporate-events", response_model=BaseResponse[CorporateEventsResponse])
async def get_corporate_events(
    ticker: str,
    period: str = Query("1Y", description="조회 기간: 1D | 1W | 1M | 1Y"),
    db: AsyncSession = Depends(get_db),
):
    """개별 종목의 기업 이벤트(실적·배당·유상증자·자사주·임원변동 등)를 반환합니다.

    한국 종목(6자리 숫자)은 yfinance + DART 두 소스를 병합해 반환합니다.
    미국 종목은 yfinance(배당·주식분할)만 반환합니다.
    """
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    ticker = ticker.upper()
    corp_code = None
    if ticker.isdigit() and len(ticker) == 6:
        from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
            CompanyRepositoryImpl,
        )
        company = await CompanyRepositoryImpl(db).find_by_stock_code(ticker)
        corp_code = company.corp_code if company else None

    result = await GetCorporateEventsUseCase(
        yfinance_port=YahooFinanceCorporateEventClient(),
        dart_client=DartCorporateEventClient(),
    ).execute(ticker=ticker, period=period, corp_code=corp_code)

    return BaseResponse.ok(data=result)


@router.get("/stocks/{ticker}/announcements", response_model=BaseResponse[AnnouncementsResponse])
async def get_announcements(
    ticker: str,
    period: str = Query("1Y", description="조회 기간: 1D | 1W | 1M | 1Y"),
    db: AsyncSession = Depends(get_db),
):
    """합병/인수/계약 공시를 반환합니다.

    한국 종목(6자리 숫자): DART 주요사항보고서
    미국 종목: SEC EDGAR 8-K 공시
    """
    if period not in _VALID_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_PERIODS))}",
        )

    ticker = ticker.upper()
    corp_code = None
    if ticker.isdigit() and len(ticker) == 6:
        from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
            CompanyRepositoryImpl,
        )
        company = await CompanyRepositoryImpl(db).find_by_stock_code(ticker)
        corp_code = company.corp_code if company else None

    result = await GetAnnouncementsUseCase(
        sec_edgar_port=SecEdgarAnnouncementClient(),
        dart_client=DartAnnouncementClient(),
    ).execute(ticker=ticker, period=period, corp_code=corp_code)

    return BaseResponse.ok(data=result)


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
