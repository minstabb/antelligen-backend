import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.infrastructure.scheduler.disclosure_jobs import (
    job_incremental_collect,
    job_refresh_company_list,
    job_process_documents,
    job_cleanup_expired_data,
    job_collect_news,
    job_seasonal_quarterly,
    job_seasonal_semiannual,
    job_seasonal_annual,
)

from app.infrastructure.scheduler.nasdaq_jobs import job_collect_nasdaq_bars
from app.infrastructure.scheduler.macro_jobs import job_refresh_market_risk

logger = logging.getLogger(__name__)

KST = "Asia/Seoul"


def create_disclosure_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=KST)

    # -- Hourly collection --

    # Every hour at :00 — incremental disclosure collection
    scheduler.add_job(
        job_incremental_collect,
        trigger=CronTrigger(minute=0, timezone=KST),
        id="incremental_collect",
        name="Incremental disclosure collection",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # -- Daily operations --

    # Daily 02:00 KST — refresh company list (DART + Naver Finance)
    scheduler.add_job(
        job_refresh_company_list,
        trigger=CronTrigger(hour=2, minute=0, timezone=KST),
        id="refresh_company_list",
        name="Refresh company list",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Daily 01:40 KST — process core disclosure documents (DART raw -> summary + RAG chunks)
    scheduler.add_job(
        job_process_documents,
        trigger=CronTrigger(hour=1, minute=40, timezone=KST),
        id="process_documents",
        name="Process disclosure documents (summary + RAG)",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Daily 03:00 KST — clean up expired data
    scheduler.add_job(
        job_cleanup_expired_data,
        trigger=CronTrigger(hour=3, minute=0, timezone=KST),
        id="cleanup_expired_data",
        name="Clean up expired data",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # Daily 06:00 KST — collect news from Naver API
    scheduler.add_job(
        job_collect_news,
        trigger=CronTrigger(hour=6, minute=0, timezone=KST),
        id="collect_news",
        name="Collect Naver news",
        replace_existing=True,
        misfire_grace_time=600,
    )


    # Daily 07:00 KST — collect NASDAQ daily bars (미국 장마감 후)
    scheduler.add_job(
        job_collect_nasdaq_bars,
        trigger=CronTrigger(hour=7, minute=0, timezone=KST),
        id="collect_nasdaq_bars",
        name="Collect NASDAQ daily OHLCV bars",

    # Daily 05:00 KST — 거시 경제 리스크 판단 스냅샷 갱신
    scheduler.add_job(
        job_refresh_market_risk,
        trigger=CronTrigger(hour=5, minute=0, timezone=KST),
        id="refresh_market_risk",
        name="Refresh macro market-risk snapshot",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # -- Seasonal report collection --

    # Quarterly report (A003): Mar, May, Aug, Nov 15th at 04:00 KST
    scheduler.add_job(
        job_seasonal_quarterly,
        trigger=CronTrigger(month="3,5,8,11", day=15, hour=4, minute=0, timezone=KST),
        id="seasonal_quarterly",
        name="Quarterly report seasonal collection",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Semi-annual report (A002): Mar, Sep 15th at 04:30 KST
    scheduler.add_job(
        job_seasonal_semiannual,
        trigger=CronTrigger(month="3,9", day=15, hour=4, minute=30, timezone=KST),
        id="seasonal_semiannual",
        name="Semi-annual report seasonal collection",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Annual report (A001): Mar, Apr 1st at 05:00 KST
    scheduler.add_job(
        job_seasonal_annual,
        trigger=CronTrigger(month="3,4", day=1, hour=5, minute=0, timezone=KST),
        id="seasonal_annual",
        name="Annual report seasonal collection",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info("Disclosure scheduler configured (9 jobs: 1 hourly, 5 daily, 3 seasonal)")
    return scheduler
