import asyncio
import json
import logging
from datetime import date
from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.app_exception import AppException
from app.common.response.base_response import BaseResponse
from app.domains.dashboard.adapter.outbound.external.fred_macro_client import FredMacroClient
from app.domains.dashboard.application.usecase.get_economic_events_usecase import (
    _REGION_SERIES,
    _SERIES_CONFIG,
)
from app.domains.history_agent.application.request.title_request import TitleBatchRequest
from app.domains.history_agent.application.response.anomaly_bar_response import (
    AnomalyBarsResponse,
)
from app.domains.history_agent.application.response.anomaly_causality_response import (
    AnomalyCausalityResponse,
)
from app.domains.history_agent.application.response.timeline_response import TimelineResponse
from app.domains.history_agent.application.response.title_response import TitleBatchResponse
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
)
from app.domains.history_agent.application.usecase.detect_anomaly_bars_usecase import (
    DetectAnomalyBarsUseCase,
)
from app.domains.history_agent.application.usecase.generate_titles_usecase import (
    GenerateTitlesUseCase,
)
from app.domains.history_agent.application.usecase.get_anomaly_causality_usecase import (
    GetAnomalyCausalityUseCase,
)
from app.domains.history_agent.application.usecase.history_agent_usecase import HistoryAgentUseCase
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_stock_client import (
    YahooFinanceStockClient,
    normalize_chart_interval,
)
from app.domains.history_agent.di import (
    get_anomaly_causality_usecase,
    get_collect_important_macro_events_usecase,
    get_fred_macro_port,
    get_generate_titles_usecase,
    get_history_agent_usecase,
)
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import get_db
from app.infrastructure.external.yahoo_ticker import normalize_yfinance_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history-agent", tags=["HistoryAgent"])

_VALID_PERIODS = {"1D", "1W", "1M", "1Y", "1Q"}  # "1Y"는 하위 호환 (→ 내부 "1Q" 매핑)
_VALID_CHART_INTERVALS = {"1D", "1W", "1M", "1Q"}
# /macro-timeline은 더 긴 역사적 범위를 커버하도록 별도 세트 사용.
_VALID_MACRO_PERIODS = {"1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y"}
_VALID_MACRO_REGIONS = {"US", "KR", "GLOBAL"}
_MACRO_CACHE_VERSION = "v1"
_SSE_KEEPALIVE_SECONDS = 15


async def _resolve_corp_code(ticker: str, db: AsyncSession) -> Optional[str]:
    if not (ticker.isdigit() and len(ticker) == 6):
        return None
    from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
        CompanyRepositoryImpl,
    )
    company = await CompanyRepositoryImpl(db).find_by_stock_code(ticker)
    return company.corp_code if company else None


@router.get("/timeline", response_model=BaseResponse[TimelineResponse])
async def get_timeline(
    ticker: str = Query(..., description="종목 코드 (예: AAPL, 005930)"),
    chart_interval: Optional[str] = Query(None, description="봉 단위: 1D | 1W | 1M | 1Q"),
    period: Optional[str] = Query(None, description="(deprecated) chart_interval 별칭. 1Y → 1Q 자동 매핑"),
    enrich_titles: bool = Query(True, description="LLM 타이틀 생성 여부. False면 rule-based 타이틀만 반환"),
    db: AsyncSession = Depends(get_db),
    usecase: HistoryAgentUseCase = Depends(get_history_agent_usecase),
):
    """CORPORATE·ANNOUNCEMENT·NEWS·MACRO 이벤트 타임라인을 반환합니다.

    §13.4 C: PRICE 카테고리는 `/anomaly-bars` 엔드포인트로 이관됨.

    - CORPORATE: 실적, 배당, 유상증자, 자사주, 임원변동
    - ANNOUNCEMENT: 합병/인수/계약 공시 (DART or SEC EDGAR)
    - NEWS: 최근 뉴스 (한국어 요약 포함)
    - MACRO: 거시 이벤트 (INDEX·ETF 경로)

    asset_type별 동작 차이:
    - EQUITY: CORPORATE·ANNOUNCEMENT·NEWS·fundamentals 수집
    - INDEX (^IXIC, ^GSPC 등): MACRO + NEWS 수집
    - ETF (SPY 등): MACRO + NEWS + holdings constituent 이벤트 수집
    - 기타(MUTUALFUND/CRYPTO 등 미지원): 빈 타임라인 + asset_type=<원본값>
    """
    effective = chart_interval or period or "1Y"
    effective = normalize_chart_interval(effective)
    if effective not in _VALID_CHART_INTERVALS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 chart_interval입니다. 사용 가능: {', '.join(sorted(_VALID_CHART_INTERVALS))}",
        )

    ticker = normalize_yfinance_ticker(ticker.upper())
    corp_code = await _resolve_corp_code(ticker, db)

    result = await usecase.execute(
        ticker=ticker, period=effective, corp_code=corp_code, enrich_titles=enrich_titles
    )
    return BaseResponse.ok(data=result)


@router.get("/timeline/stream")
async def stream_timeline(
    ticker: str = Query(..., description="종목 코드 (예: AAPL, 005930)"),
    chart_interval: Optional[str] = Query(None, description="봉 단위: 1D | 1W | 1M | 1Q"),
    period: Optional[str] = Query(None, description="(deprecated) chart_interval 별칭"),
    enrich_titles: bool = Query(True, description="LLM 타이틀 생성 여부. False면 rule-based 타이틀만 반환"),
    db: AsyncSession = Depends(get_db),
    usecase: HistoryAgentUseCase = Depends(get_history_agent_usecase),
):
    """타임라인 데이터를 SSE로 스트리밍합니다. progress / done / error 이벤트를 순서대로 전송합니다.

    클라이언트 disconnect 시 백그라운드 태스크를 취소해 불필요한 LLM/외부 호출을 차단합니다.
    15초마다 keepalive 프레임(`: ping`)을 송신합니다.
    """
    effective = chart_interval or period or "1Y"
    effective = normalize_chart_interval(effective)
    if effective not in _VALID_CHART_INTERVALS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 chart_interval입니다. 사용 가능: {', '.join(sorted(_VALID_CHART_INTERVALS))}",
        )
    period = effective  # 내부 변수는 그대로 period 이름 유지(UseCase 파라미터 호환)

    ticker = normalize_yfinance_ticker(ticker.upper())
    corp_code = await _resolve_corp_code(ticker, db)

    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(step: str, label: str, pct: int) -> None:
        try:
            await queue.put({"type": "progress", "step": step, "label": label, "pct": pct})
        except Exception as exc:  # pragma: no cover — queue put은 실제로 실패 불가
            logger.warning("[stream_timeline] progress 이벤트 전송 실패: %s", exc)

    async def _run() -> None:
        try:
            result = await usecase.execute(
                ticker=ticker,
                period=period,
                corp_code=corp_code,
                on_progress=on_progress,
                enrich_titles=enrich_titles,
            )
            await queue.put({"type": "done", "data": result.model_dump_json()})
        except asyncio.CancelledError:
            logger.info("[stream_timeline] 백그라운드 태스크 취소됨 (ticker=%s)", ticker)
            raise
        except Exception as exc:
            logger.exception(
                "[stream_timeline] 오류 ticker=%s period=%s error_type=%s",
                ticker, period, type(exc).__name__,
            )
            await queue.put({"type": "error", "message": "타임라인 데이터 처리 중 오류가 발생했습니다."})

    task = asyncio.create_task(_run())

    async def _event_generator():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    # LB/프록시 idle timeout 회피용 heartbeat
                    yield ": ping\n\n"
                    continue

                if item["type"] == "progress":
                    data = json.dumps(
                        {"step": item["step"], "label": item["label"], "pct": item["pct"]}
                    )
                    yield f"event: progress\ndata: {data}\n\n"
                elif item["type"] == "done":
                    yield f"event: done\ndata: {item['data']}\n\n"
                    return
                elif item["type"] == "error":
                    data = json.dumps({"message": item["message"]})
                    yield f"event: error\ndata: {data}\n\n"
                    return
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/macro-timeline", response_model=BaseResponse[TimelineResponse])
async def get_macro_timeline(
    period: str = Query("1Y", description=f"기간: {', '.join(sorted(_VALID_MACRO_PERIODS))}"),
    region: str = Query("US", description="리전: US | KR | GLOBAL"),
    limit: Optional[int] = Query(
        None, ge=1, le=100, description="반환 이벤트 수 (미지정 시 macro_timeline_top_n)",
    ),
    redis: aioredis.Redis = Depends(get_redis),
    usecase: CollectImportantMacroEventsUseCase = Depends(
        get_collect_important_macro_events_usecase,
    ),
):
    """티커와 무관하게 '역사적으로 중요한' 매크로 이벤트만 반환한다.

    소스: 큐레이션 카탈로그(JSON seed) + FRED 서프라이즈 릴리스 + 관련자산 스파이크 + GPR.
    LLM 중요도 랭커가 점수화하여 Top-N만 유지. 결과는 Redis에 24h 캐시.
    """
    region_upper = region.upper()
    if region_upper not in _VALID_MACRO_REGIONS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 region입니다. 사용 가능: {', '.join(sorted(_VALID_MACRO_REGIONS))}",
        )
    period_upper = period.upper()
    if period_upper not in _VALID_MACRO_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_MACRO_PERIODS))}",
        )

    settings = get_settings()
    effective_limit = limit if limit is not None else settings.macro_timeline_top_n
    cache_key = f"macro_timeline:{_MACRO_CACHE_VERSION}:{region_upper}:{period_upper}:{effective_limit}"

    cached = await redis.get(cache_key)
    if cached:
        try:
            return BaseResponse.ok(data=TimelineResponse.model_validate_json(cached))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[macro-timeline] 캐시 디코드 실패: %s", exc)

    events = await usecase.execute(
        region=region_upper, period=period_upper, top_n=effective_limit,
    )
    response = TimelineResponse(
        ticker=None,
        period=period_upper,
        count=len(events),
        events=events,
        region=region_upper,
        asset_type="MACRO",
    )
    await redis.setex(cache_key, settings.macro_cache_ttl_seconds, response.model_dump_json())
    return BaseResponse.ok(data=response)


@router.get("/macro-timeline/stream")
async def stream_macro_timeline(
    period: str = Query("1Y", description=f"기간: {', '.join(sorted(_VALID_MACRO_PERIODS))}"),
    region: str = Query("US", description="리전: US | KR | GLOBAL"),
    limit: Optional[int] = Query(
        None, ge=1, le=100, description="반환 이벤트 수 (미지정 시 macro_timeline_top_n)",
    ),
    redis: aioredis.Redis = Depends(get_redis),
    usecase: CollectImportantMacroEventsUseCase = Depends(
        get_collect_important_macro_events_usecase,
    ),
):
    """macro-timeline을 SSE로 스트리밍. 장기 period(5Y/10Y) cold 요청 UX 개선용.

    캐시 적중 시 즉시 done 이벤트 1개만 전송. 미적중 시 collect/rank/finalize
    단계별 progress 이벤트를 송신하고 완료 시 done 이벤트로 응답 전체 전달.
    클라이언트 disconnect 시 백그라운드 태스크를 취소한다.
    """
    region_upper = region.upper()
    if region_upper not in _VALID_MACRO_REGIONS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 region입니다. 사용 가능: {', '.join(sorted(_VALID_MACRO_REGIONS))}",
        )
    period_upper = period.upper()
    if period_upper not in _VALID_MACRO_PERIODS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 period입니다. 사용 가능: {', '.join(sorted(_VALID_MACRO_PERIODS))}",
        )

    settings = get_settings()
    effective_limit = limit if limit is not None else settings.macro_timeline_top_n
    cache_key = (
        f"macro_timeline:{_MACRO_CACHE_VERSION}:{region_upper}:{period_upper}:{effective_limit}"
    )

    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(step: str, label: str, pct: int) -> None:
        try:
            await queue.put({"type": "progress", "step": step, "label": label, "pct": pct})
        except Exception as exc:  # pragma: no cover
            logger.warning("[stream_macro_timeline] progress 전송 실패: %s", exc)

    async def _run() -> None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                try:
                    TimelineResponse.model_validate_json(cached)
                    await queue.put({"type": "done", "data": cached.decode() if isinstance(cached, (bytes, bytearray)) else cached})
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[stream_macro_timeline] 캐시 디코드 실패: %s", exc)

            events = await usecase.execute(
                region=region_upper,
                period=period_upper,
                top_n=effective_limit,
                on_progress=on_progress,
            )
            response = TimelineResponse(
                ticker=None,
                period=period_upper,
                count=len(events),
                events=events,
                region=region_upper,
                asset_type="MACRO",
            )
            payload = response.model_dump_json()
            await redis.setex(cache_key, settings.macro_cache_ttl_seconds, payload)
            await queue.put({"type": "done", "data": payload})
        except asyncio.CancelledError:
            logger.info("[stream_macro_timeline] 태스크 취소 (region=%s period=%s)",
                        region_upper, period_upper)
            raise
        except Exception as exc:
            logger.exception(
                "[stream_macro_timeline] 오류 region=%s period=%s error_type=%s",
                region_upper, period_upper, type(exc).__name__,
            )
            await queue.put({"type": "error", "message": "매크로 타임라인 생성 중 오류가 발생했습니다."})

    task = asyncio.create_task(_run())

    async def _event_generator():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                if item["type"] == "progress":
                    data = json.dumps(
                        {"step": item["step"], "label": item["label"], "pct": item["pct"]}
                    )
                    yield f"event: progress\ndata: {data}\n\n"
                elif item["type"] == "done":
                    yield f"event: done\ndata: {item['data']}\n\n"
                    return
                elif item["type"] == "error":
                    data = json.dumps({"message": item["message"]})
                    yield f"event: error\ndata: {data}\n\n"
                    return
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/anomaly-bars", response_model=BaseResponse[AnomalyBarsResponse])
async def get_anomaly_bars(
    ticker: str = Query(..., description="종목 코드"),
    chart_interval: Optional[str] = Query(None, description="봉 단위: 1D | 1W | 1M | 1Q"),
    period: Optional[str] = Query(None, description="(deprecated) chart_interval 별칭"),
):
    """차트 이상치 봉(★ 마커 대상)을 반환합니다. §13.4 C 설계로 PRICE 카테고리를 대체.

    봉 단위별 adaptive threshold (k=2.5 × σ + floor) 로 평상시 대비 특이한 봉만 선별.
    """
    effective = chart_interval or period or "1D"
    effective = normalize_chart_interval(effective)
    if effective not in _VALID_CHART_INTERVALS:
        raise AppException(
            status_code=400,
            message=f"유효하지 않은 chart_interval입니다. 사용 가능: {', '.join(sorted(_VALID_CHART_INTERVALS))}",
        )

    ticker = normalize_yfinance_ticker(ticker.upper())
    usecase = DetectAnomalyBarsUseCase(stock_bars_port=YahooFinanceStockClient())
    result = await usecase.execute(ticker=ticker, chart_interval=effective)
    return BaseResponse.ok(data=result)


@router.get(
    "/anomaly-bars/{ticker}/{bar_date}/causality",
    response_model=BaseResponse[AnomalyCausalityResponse],
)
async def get_anomaly_causality(
    ticker: str,
    bar_date: date,
    usecase: GetAnomalyCausalityUseCase = Depends(get_anomaly_causality_usecase),
):
    """이상치 봉 1건의 causality(인과 가설)를 lazy-fetch한다.

    프론트 차트 ★ 마커 클릭 시 호출. DB 캐시 히트면 즉시 반환, 미스면 causality
    agent 워크플로우를 실행하고 결과를 저장한다.
    """
    ticker_norm = normalize_yfinance_ticker(ticker.upper())
    result = await usecase.execute(ticker=ticker_norm, bar_date=bar_date)
    return BaseResponse.ok(data=result)


@router.post("/titles", response_model=BaseResponse[TitleBatchResponse])
async def generate_titles(
    request: TitleBatchRequest = Body(...),
    usecase: GenerateTitlesUseCase = Depends(get_generate_titles_usecase),
):
    """이벤트 배치의 LLM 타이틀을 생성한다. DB 캐시 히트분은 즉시 반환."""
    result = await usecase.execute(request)
    return BaseResponse.ok(data=result)


@router.get("/admin/fred/health")
async def fred_series_health(
    fred_client: FredMacroClient = Depends(get_fred_macro_port),
):
    """_REGION_SERIES에 등록된 FRED 시리즈가 최근 3개월 동안 실제 데이터를 반환하는지 확인한다.

    응답:
        {
          "series": [
            {"series_id": "FEDFUNDS", "region": "US", "label": "기준금리", "points": 3, "ok": true},
            ...
          ],
          "empty_series": ["INTDSRKRM193N", ...]
        }
    """
    results = []
    empty_series: list[str] = []

    for region, series_ids in _REGION_SERIES.items():
        for sid in series_ids:
            event_type, label, _, _ = _SERIES_CONFIG[sid]
            try:
                data = await fred_client.fetch_series(sid, 3)
                points = len(data)
                ok = points > 0
                if not ok:
                    empty_series.append(sid)
                    logger.warning(
                        "[FredHealth] 빈 시리즈: series=%s region=%s label=%s",
                        sid, region, label,
                    )
            except Exception as exc:
                points = 0
                ok = False
                empty_series.append(sid)
                logger.warning(
                    "[FredHealth] 시리즈 조회 예외: series=%s error=%s", sid, exc,
                )

            results.append({
                "series_id": sid,
                "region": region,
                "event_type": event_type,
                "label": label,
                "points": points,
                "ok": ok,
            })

    return BaseResponse.ok(data={"series": results, "empty_series": empty_series})
