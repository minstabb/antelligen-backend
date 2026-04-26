import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.adapter.inbound.api.v1_router import api_v1_router
from app.domains.stock_theme.adapter.outbound.persistence.stock_theme_repository_impl import StockThemeRepositoryImpl
from app.domains.stock_theme.application.usecase.seed_stock_themes_usecase import SeedStockThemesUseCase
from app.domains.authentication.adapter.inbound.api.authentication_router import router as authentication_router
from app.common.exception.global_exception_handler import register_exception_handlers
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.config.logging_config import setup_logging
from app.infrastructure.config.langsmith_config import configure_langsmith
from app.infrastructure.database.database import AsyncSessionLocal, Base, engine, check_db_health
from app.infrastructure.database.vector_database import VectorBase, vector_engine

import app.domains.account.infrastructure.orm.account_orm  # noqa: F401
import app.domains.account.infrastructure.orm.user_watchlist_orm  # noqa: F401
import app.domains.news.infrastructure.orm.saved_article_orm  # noqa: F401
import app.domains.news.infrastructure.orm.user_saved_article_orm  # noqa: F401
import app.domains.news.infrastructure.orm.article_content_orm  # noqa: F401
import app.domains.board.infrastructure.orm.board_orm  # noqa: F401
import app.domains.post.infrastructure.orm.post_orm  # noqa: F401
import app.domains.stock.infrastructure.orm.stock_vector_document_orm  # noqa: F401
import app.domains.stock_theme.infrastructure.orm.stock_theme_orm  # noqa: F401
import app.domains.news.infrastructure.orm.collected_news_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.company_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.company_data_coverage_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.disclosure_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.disclosure_document_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.collection_job_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.collection_job_item_orm  # noqa: F401
import app.domains.disclosure.infrastructure.orm.rag_document_chunk_orm  # noqa: F401
import app.domains.agent.infrastructure.orm.integrated_analysis_orm  # noqa: F401
import app.domains.investment.infrastructure.orm.investment_youtube_log_orm  # noqa: F401
import app.domains.investment.infrastructure.orm.investment_youtube_video_orm  # noqa: F401
import app.domains.investment.infrastructure.orm.investment_youtube_video_comment_orm  # noqa: F401
import app.domains.investment.infrastructure.orm.investment_news_content_orm  # noqa: F401
import app.domains.news.infrastructure.orm.investment_news_orm  # noqa: F401
import app.domains.schedule.infrastructure.orm.economic_event_orm  # noqa: F401
import app.domains.dashboard.infrastructure.orm.nasdaq_bar_orm  # noqa: F401
import app.domains.history_agent.infrastructure.orm.event_enrichment_orm  # noqa: F401
import app.domains.stock.market_data.infrastructure.orm.daily_bar_orm  # noqa: F401
import app.domains.stock.market_data.infrastructure.orm.popular_stock_ticker_orm  # noqa: F401
import app.domains.stock.market_data.infrastructure.orm.event_impact_metric_orm  # noqa: F401
import app.domains.smart_money.infrastructure.orm.investor_flow_orm  # noqa: F401
import app.domains.smart_money.infrastructure.orm.global_portfolio_orm  # noqa: F401
import app.domains.smart_money.infrastructure.orm.kr_portfolio_orm  # noqa: F401

setup_logging()
configure_langsmith()

settings: Settings = get_settings()


async def _try_restore_macro_snapshot(max_age_hours: int) -> bool:
    """Redis 에 저장된 매크로 스냅샷이 충분히 신선하면 메모리 store 로 복원.

    프로세스 재시작 / hot-reload 시 YouTube/LLM 재호출을 회피한다.
    복원 성공 시 True, 캐시 없음/만료/파싱 실패 시 False.
    """
    import json
    from datetime import timedelta

    from app.domains.macro.adapter.outbound.cache.market_risk_snapshot_store import (
        get_market_risk_snapshot_store,
    )
    from app.domains.macro.application.response.market_risk_judgement_response import (
        MarketRiskJudgementResponse,
    )
    from app.infrastructure.cache.redis_client import redis_client
    from app.infrastructure.scheduler.macro_jobs import MACRO_SNAPSHOT_REDIS_KEY

    try:
        raw = await redis_client.get(MACRO_SNAPSHOT_REDIS_KEY)
        if not raw:
            return False
        payload = json.loads(raw)
        updated_at = datetime.fromisoformat(payload["updated_at"])
        if datetime.now() - updated_at > timedelta(hours=max_age_hours):
            return False
        response = MarketRiskJudgementResponse.model_validate(payload["response"])
        get_market_risk_snapshot_store().set(response, updated_at=updated_at)
        return True
    except Exception as e:
        logging.getLogger(__name__).warning(
            "[Startup] Macro snapshot restore from Redis failed: %s", e
        )
        return False


@asynccontextmanager
async def lifespan(application: FastAPI):
    if not await check_db_health():
        raise RuntimeError("PostgreSQL 연결 실패 — 서버를 시작할 수 없습니다.")

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    async with vector_engine.begin() as conn:
        await conn.run_sync(VectorBase.metadata.create_all)

    # Seed stock themes
    async with AsyncSessionLocal() as session:
        await SeedStockThemesUseCase(StockThemeRepositoryImpl(session)).execute()

    # Bootstrap initial data (runs only when companies table is empty)
    from app.infrastructure.scheduler.disclosure_jobs import (
        job_bootstrap,
        job_collect_news,
        job_incremental_collect,
        job_refresh_company_list,
        job_process_documents,
    )

    try:
        await job_bootstrap()
    except Exception as e:
        logging.getLogger(__name__).error("Bootstrap failed (server continues normally): %s", str(e))

    try:
        await job_collect_news()
    except Exception as e:
        logging.getLogger(__name__).error("News bootstrap failed (server continues normally): %s", str(e))

    # Catch-up scheduled jobs on server startup (skip when recently run)
    from datetime import timedelta

    from app.domains.disclosure.adapter.outbound.persistence.collection_job_repository_impl import (
        CollectionJobRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.disclosure_repository_impl import (
        DisclosureRepositoryImpl,
    )

    try:
        await job_incremental_collect()
    except Exception as e:
        logging.getLogger(__name__).error(
            "Incremental collect on startup failed (server continues normally): %s", str(e)
        )

    try:
        async with AsyncSessionLocal() as session:
            latest = await CollectionJobRepositoryImpl(session).find_latest_by_job_name(
                "refresh_company_list"
            )
            should_run = (
                latest is None
                or latest.status != "success"
                or latest.started_at is None
                or (datetime.now() - latest.started_at) > timedelta(hours=24)
            )
        if should_run:
            await job_refresh_company_list()
        else:
            logging.getLogger(__name__).info(
                "[Startup] refresh_company_list skipped (last success < 24h)"
            )
    except Exception as e:
        logging.getLogger(__name__).error(
            "Refresh company list on startup failed (server continues normally): %s", str(e)
        )

    try:
        async with AsyncSessionLocal() as session:
            unprocessed = await DisclosureRepositoryImpl(session).find_unprocessed_core(limit=1)
        if unprocessed:
            await job_process_documents()
        else:
            logging.getLogger(__name__).info(
                "[Startup] process_documents skipped (no unprocessed core disclosures)"
            )
    except Exception as e:
        logging.getLogger(__name__).error(
            "Process documents on startup failed (server continues normally): %s", str(e)
        )

    from app.infrastructure.scheduler.nasdaq_jobs import job_bootstrap_nasdaq

    try:
        await job_bootstrap_nasdaq()
    except Exception as e:
        logging.getLogger(__name__).error("Nasdaq bootstrap failed (server continues normally): %s", str(e))

    from app.infrastructure.scheduler.stock_bars_jobs import job_bootstrap_stock_bars

    try:
        await job_bootstrap_stock_bars()
    except Exception as e:
        logging.getLogger(__name__).error(
            "Stock bars bootstrap failed (server continues normally): %s", str(e)
        )

    # 거시 경제 리스크 스냅샷 — Redis 영속 캐시가 4h 이내면 복원, 아니면 신규 생성.
    # YouTube/LLM quota 절약 목적: 코드 hot-reload 마다 매번 호출되는 것을 방지한다.
    from app.infrastructure.scheduler.macro_jobs import job_refresh_market_risk

    try:
        restored = await _try_restore_macro_snapshot(max_age_hours=4)
        if restored:
            logging.getLogger(__name__).info(
                "[Startup] Macro snapshot restored from Redis (skip bootstrap)"
            )
        else:
            await job_refresh_market_risk()
    except Exception as e:
        logging.getLogger(__name__).error(
            "Macro snapshot bootstrap failed (server continues normally): %s", str(e)
        )

    # 잠정실적 일정 최초 적재 (이후 분기 초 + 주간으로 스케줄러가 재수집)
    from app.infrastructure.scheduler.corp_earnings_jobs import job_refresh_corp_earnings

    try:
        await job_refresh_corp_earnings()
    except Exception as e:
        logging.getLogger(__name__).error(
            "Corp earnings bootstrap failed (server continues normally): %s", str(e)
        )

    from app.infrastructure.scheduler.disclosure_scheduler import create_disclosure_scheduler

    scheduler = create_disclosure_scheduler()
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allowed_frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Cookie", "Set-Cookie"],
)

app.include_router(api_v1_router)
app.include_router(authentication_router)
register_exception_handlers(app)


@app.get("/")
async def root():
    return {"message": "Hello World"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=33333)
