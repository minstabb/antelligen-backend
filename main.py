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

setup_logging()
configure_langsmith()

settings: Settings = get_settings()


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

    # 거시 경제 리스크 스냅샷 최초 로딩 (이후 매일 새벽 5시에 스케줄러가 갱신)
    from app.infrastructure.scheduler.macro_jobs import job_refresh_market_risk

    try:
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
