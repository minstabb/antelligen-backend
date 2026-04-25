import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response.base_response import BaseResponse
from app.domains.schedule.adapter.outbound.external.composite_economic_event_client import (
    CompositeEconomicEventClient,
)
from app.domains.schedule.adapter.outbound.external.fred_economic_event_client import (
    FredEconomicEventClient,
)
from app.domains.schedule.adapter.outbound.external.composite_investment_info_provider import (
    CompositeInvestmentInfoProvider,
)
from app.domains.schedule.adapter.outbound.external.fred_investment_info_client import (
    FredInvestmentInfoClient,
)
from app.domains.schedule.adapter.outbound.external.static_central_bank_event_client import (
    StaticCentralBankEventClient,
)
from app.domains.schedule.adapter.outbound.external.dart_corp_earnings_client import (
    DartCorpEarningsClient,
)
from app.domains.schedule.adapter.outbound.external.yahoo_investment_info_client import (
    YahooInvestmentInfoClient,
)
from app.domains.schedule.adapter.outbound.external.openai_event_impact_analyzer import (
    OpenAIEventImpactAnalyzer,
)
from app.domains.schedule.adapter.outbound.messaging.notification_broadcaster import (
    get_notification_broadcaster,
)
from app.domains.schedule.adapter.outbound.messaging.schedule_notification_publisher_impl import (
    ScheduleNotificationPublisher,
)
from app.domains.schedule.adapter.outbound.persistence.economic_event_repository_impl import (
    EconomicEventRepositoryImpl,
)
from app.domains.schedule.adapter.outbound.persistence.event_impact_analysis_repository_impl import (
    EventImpactAnalysisRepositoryImpl,
)
from app.domains.schedule.adapter.outbound.persistence.schedule_notification_repository_impl import (
    ScheduleNotificationRepositoryImpl,
)
from app.domains.schedule.application.request.search_investment_info_request import (
    SearchInvestmentInfoRequest,
)
from app.domains.schedule.application.request.run_event_analysis_request import (
    RunEventAnalysisRequest,
)
from app.domains.schedule.application.request.sync_economic_events_request import (
    SyncEconomicEventsRequest,
)
from app.domains.schedule.application.response.economic_event_response import (
    GetEconomicEventsResponse,
    SyncEconomicEventsResponse,
)
from app.domains.schedule.application.response.event_impact_analysis_response import (
    RunEventAnalysisResponse,
)
from app.domains.schedule.application.response.investment_info_response import (
    SearchInvestmentInfoResponse,
)
from app.domains.schedule.application.response.schedule_notification_response import (
    ListScheduleNotificationsResponse,
    MarkAllScheduleNotificationsReadResponse,
    MarkScheduleNotificationReadResponse,
)
from app.domains.schedule.application.usecase.get_economic_events_usecase import (
    GetEconomicEventsUseCase,
)
from app.domains.schedule.application.usecase.list_schedule_notifications_usecase import (
    ListScheduleNotificationsUseCase,
)
from app.domains.schedule.application.usecase.mark_schedule_notification_read_usecase import (
    MarkScheduleNotificationReadUseCase,
)
from app.domains.schedule.application.usecase.run_event_impact_analysis_usecase import (
    RunEventImpactAnalysisUseCase,
)
from app.domains.schedule.application.usecase.search_investment_info_usecase import (
    SearchInvestmentInfoUseCase,
)
from app.domains.schedule.application.usecase.sync_economic_events_usecase import (
    SyncEconomicEventsUseCase,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import get_db
from app.infrastructure.external.openai_responses_client import get_openai_responses_client

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("", summary="schedule 도메인 엔드포인트 안내")
@router.get("/", summary="schedule 도메인 엔드포인트 안내", include_in_schema=False)
async def schedule_index():
    return BaseResponse.ok(
        data={
            "endpoints": [
                {"method": "GET",  "path": "/api/v1/schedule/investment-info",
                 "desc": "금리·유가·환율·VIX·DXY·주요 지수·금·USD/JPY·UST 2/10/20y·KOSPI200·디램익스체인지·BDI 조회"},
                {"method": "POST", "path": "/api/v1/schedule/investment-info",
                 "desc": "위와 동일 (JSON body)"},
                {"method": "POST", "path": "/api/v1/schedule/economic-events/sync",
                 "desc": "주요 경제 일정 동기화 (FRED + Fed/BOE/BOJ/BOK)"},
                {"method": "GET",  "path": "/api/v1/schedule/economic-events",
                 "desc": "저장된 경제 일정 조회 (year, country, importance)"},
                {"method": "POST", "path": "/api/v1/schedule/event-analysis/run",
                 "desc": "경제 일정별 영향 분석 실행 (LLM)"},
                {"method": "GET",  "path": "/api/v1/schedule/event-analysis",
                 "desc": "저장된 영향 분석 조회"},
                {"method": "GET",  "path": "/api/v1/schedule/notifications",
                 "desc": "분석 저장 알림 목록 (unread_only, limit)"},
                {"method": "POST", "path": "/api/v1/schedule/notifications/{id}/read",
                 "desc": "개별 알림 읽음 처리"},
                {"method": "POST", "path": "/api/v1/schedule/notifications/read-all",
                 "desc": "전체 알림 읽음 처리"},
                {"method": "GET",  "path": "/api/v1/schedule/notifications/stream",
                 "desc": "알림 실시간 구독 (SSE)"},
            ],
        },
        message="schedule 도메인 API 목록",
    )


def _build_usecase() -> SearchInvestmentInfoUseCase:
    """FRED 를 1순위로, Yahoo 를 fallback 으로 연결한 투자 정보 provider 조립."""
    settings = get_settings()
    provider = CompositeInvestmentInfoProvider(
        providers=[
            FredInvestmentInfoClient(api_key=settings.fred_api_key),
            YahooInvestmentInfoClient(),
        ]
    )
    return SearchInvestmentInfoUseCase(provider=provider)


@router.get(
    "/investment-info",
    response_model=BaseResponse[SearchInvestmentInfoResponse],
    summary="투자 정보 검색 (금리·유가·환율·VIX·DXY·주요 지수·금·USD/JPY·UST 2·10·20y·KOSPI200)",
)
async def get_investment_info(
    types: Optional[List[str]] = Query(
        default=None,
        description="investment info types. 예: interest_rate, oil_price, exchange_rate 또는 한글 금리/유가/환율",
    ),
):
    """쿼리 스트링으로 복수 유형을 받아 FRED(1순위) · Yahoo(fallback) 에서 조회한다.
    미지정 시 확장된 기본 세트(금리·유가·환율·VIX·DXY·S&P500·NASDAQ100·KOSPI200·금·USD/JPY·UST 2/10/20y) 조회."""
    print(f"[schedule.router] GET /schedule/investment-info types={types}")
    default_types = [
        "interest_rate", "oil_price", "exchange_rate",
        "vix", "dxy", "sp_500", "nasdaq_100", "kospi_200",
        "gold", "usd_jpy", "us_t2y", "us_t10y", "us_t20y",
        "dram_exchange", "baltic_dry_index",
    ]
    resolved_types = types if types else default_types
    request = SearchInvestmentInfoRequest(types=resolved_types)
    result = await _build_usecase().execute(request)
    return BaseResponse.ok(data=result, message="투자 정보 조회 완료")


@router.post(
    "/investment-info",
    response_model=BaseResponse[SearchInvestmentInfoResponse],
    summary="투자 정보 검색 (JSON body) — FRED",
)
async def post_investment_info(request: SearchInvestmentInfoRequest = Body(...)):
    print(f"[schedule.router] POST /schedule/investment-info types={request.types}")
    result = await _build_usecase().execute(request)
    return BaseResponse.ok(data=result, message="투자 정보 조회 완료")


# ─────────────────────────────────────────
# 주요 경제 일정 (FRED releases) — 동기화 + 조회
# ─────────────────────────────────────────


@router.post(
    "/economic-events/sync",
    response_model=BaseResponse[SyncEconomicEventsResponse],
    summary="주요 경제 일정 동기화 (FRED + Fed·BOE·BOJ·BOK 기준금리 발표) — 기준 연도 ± 1년 저장",
)
async def sync_economic_events(
    request: SyncEconomicEventsRequest = Body(default_factory=SyncEconomicEventsRequest),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    fetch_port = CompositeEconomicEventClient(
        clients=[
            FredEconomicEventClient(api_key=settings.fred_api_key),
            StaticCentralBankEventClient(),
            DartCorpEarningsClient(api_key=settings.open_dart_api_key),
        ]
    )
    repository = EconomicEventRepositoryImpl(db=db)
    usecase = SyncEconomicEventsUseCase(fetch_port=fetch_port, repository=repository)
    result = await usecase.execute(request)
    return BaseResponse.ok(data=result, message="경제 일정 동기화 완료")


@router.get(
    "/economic-events",
    response_model=BaseResponse[GetEconomicEventsResponse],
    summary="저장된 주요 경제 일정 조회",
)
async def list_economic_events(
    year: Optional[int] = Query(default=None, description="조회 연도. 미지정 시 현재 연도"),
    country: Optional[str] = Query(default=None, description="국가 코드 (예: US)"),
    importance: Optional[str] = Query(default=None, description="HIGH / MEDIUM / LOW"),
    db: AsyncSession = Depends(get_db),
):
    repository = EconomicEventRepositoryImpl(db=db)
    usecase = GetEconomicEventsUseCase(repository=repository)
    result = await usecase.execute(year=year, country=country, importance=importance)
    return BaseResponse.ok(data=result, message="경제 일정 조회 완료")


# ─────────────────────────────────────────
# 경제 일정별 영향 분석 (LLM 기반) — 실행 + 조회
# ─────────────────────────────────────────


@router.post(
    "/event-analysis/run",
    response_model=BaseResponse[RunEventAnalysisResponse],
    summary="저장된 경제 일정별 영향 분석 실행 (LLM + 매크로 지표 스냅샷)",
)
async def run_event_analysis(
    request: RunEventAnalysisRequest = Body(default_factory=RunEventAnalysisRequest),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    event_repo = EconomicEventRepositoryImpl(db=db)
    analysis_repo = EventImpactAnalysisRepositoryImpl(db=db)
    indicator_provider = CompositeInvestmentInfoProvider(
        providers=[
            FredInvestmentInfoClient(api_key=settings.fred_api_key),
            YahooInvestmentInfoClient(),
        ]
    )
    analyzer = OpenAIEventImpactAnalyzer(client=get_openai_responses_client())
    notification_publisher = ScheduleNotificationPublisher(
        repository=ScheduleNotificationRepositoryImpl(db=db),
        broadcaster=get_notification_broadcaster(),
    )
    usecase = RunEventImpactAnalysisUseCase(
        event_repository=event_repo,
        analysis_repository=analysis_repo,
        indicator_provider=indicator_provider,
        analyzer=analyzer,
        model_name=settings.openai_learning_model,
        notification_publisher=notification_publisher,
    )
    result = await usecase.execute(request)
    return BaseResponse.ok(data=result, message="경제 일정 영향 분석 완료")


@router.get(
    "/event-analysis",
    response_model=BaseResponse[RunEventAnalysisResponse],
    summary="경제 일정 영향 분석 조회 (필요 시 자동 생성) + 다가오는 일주일 일정",
)
async def list_event_analysis(
    country: Optional[str] = Query(default=None, description="국가 코드 (예: US, KR)"),
    days_back: int = Query(default=14, ge=0, le=365),
    days_forward: int = Query(default=14, ge=0, le=365),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """기준일(주말은 금요일로 시프트) 기준 경제 일정 분석 + 다가오는 7일 일정을 반환.

    - 기존 분석이 있으면 **LLM 호출 없이** DB에서 즉시 반환 (skipped_existing)
    - 분석이 없으면 자동으로 한 번 실행해 저장 후 반환 (lazy run)
    - `POST /event-analysis/run` 은 force_refresh 같은 옵션을 위한 explicit endpoint
    """
    print(
        f"[schedule.router] GET /schedule/event-analysis country={country} "
        f"days_back={days_back} days_forward={days_forward} limit={limit}"
    )
    settings = get_settings()
    event_repo = EconomicEventRepositoryImpl(db=db)
    analysis_repo = EventImpactAnalysisRepositoryImpl(db=db)
    indicator_provider = CompositeInvestmentInfoProvider(
        providers=[
            FredInvestmentInfoClient(api_key=settings.fred_api_key),
            YahooInvestmentInfoClient(),
        ]
    )
    analyzer = OpenAIEventImpactAnalyzer(client=get_openai_responses_client())
    notification_publisher = ScheduleNotificationPublisher(
        repository=ScheduleNotificationRepositoryImpl(db=db),
        broadcaster=get_notification_broadcaster(),
    )
    usecase = RunEventImpactAnalysisUseCase(
        event_repository=event_repo,
        analysis_repository=analysis_repo,
        indicator_provider=indicator_provider,
        analyzer=analyzer,
        model_name=settings.openai_learning_model,
        notification_publisher=notification_publisher,
    )
    result = await usecase.execute(
        RunEventAnalysisRequest(
            days_back=days_back,
            days_forward=days_forward,
            country=country,
            limit=limit,
            force_refresh=False,
        )
    )
    return BaseResponse.ok(data=result, message="경제 일정 영향 분석 조회 완료")


# ─────────────────────────────────────────
# 저장 결과 알림 — 목록/읽음/SSE 스트림
# ─────────────────────────────────────────


@router.get(
    "/notifications",
    response_model=BaseResponse[ListScheduleNotificationsResponse],
    summary="경제 일정 분석 저장 알림 목록",
)
async def list_schedule_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False, description="True 시 미확인만 반환"),
    db: AsyncSession = Depends(get_db),
):
    print(
        f"[schedule.router] GET /schedule/notifications limit={limit} unread_only={unread_only}"
    )
    repo = ScheduleNotificationRepositoryImpl(db=db)
    usecase = ListScheduleNotificationsUseCase(repository=repo)
    result = await usecase.execute(limit=limit, unread_only=unread_only)
    return BaseResponse.ok(data=result, message="알림 목록 조회 완료")


@router.post(
    "/notifications/{notification_id}/read",
    response_model=BaseResponse[MarkScheduleNotificationReadResponse],
    summary="알림 1건을 읽음 처리",
)
async def mark_schedule_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
):
    print(f"[schedule.router] POST /schedule/notifications/{notification_id}/read")
    repo = ScheduleNotificationRepositoryImpl(db=db)
    usecase = MarkScheduleNotificationReadUseCase(repository=repo)
    result = await usecase.execute_single(notification_id)
    return BaseResponse.ok(data=result, message="알림 읽음 처리 완료")


@router.post(
    "/notifications/read-all",
    response_model=BaseResponse[MarkAllScheduleNotificationsReadResponse],
    summary="미확인 알림 전체 읽음 처리",
)
async def mark_all_schedule_notifications_read(
    db: AsyncSession = Depends(get_db),
):
    print("[schedule.router] POST /schedule/notifications/read-all")
    repo = ScheduleNotificationRepositoryImpl(db=db)
    usecase = MarkScheduleNotificationReadUseCase(repository=repo)
    result = await usecase.execute_all()
    return BaseResponse.ok(data=result, message="전체 알림 읽음 처리 완료")


@router.get(
    "/notifications/stream",
    summary="저장 결과 알림 실시간 구독 (Server-Sent Events)",
)
async def stream_schedule_notifications():
    """새 알림을 실시간으로 push 하는 SSE 스트림.

    - Content-Type: text/event-stream
    - 30초마다 ``: keep-alive`` 주석 라인으로 heartbeat 전송
    - 연결 종료 시 자동으로 구독 해제
    """
    print("[schedule.router] GET /schedule/notifications/stream (SSE 연결)")
    broadcaster = get_notification_broadcaster()
    queue = await broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    data = json.dumps(payload, default=str, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            print("[schedule.router] SSE 연결 취소됨")
            raise
        finally:
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
