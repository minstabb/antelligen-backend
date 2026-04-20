import logging
import time

from app.infrastructure.database.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def job_bootstrap_nasdaq():
    """서버 시작 시 1회 실행 — nasdaq_bars 테이블이 비어있으면 30년치 데이터를 수집한다.

    데이터가 이미 존재하면 즉시 종료한다 (중복 수집 방지).
    """
    from app.domains.dashboard.adapter.outbound.external.yahoo_finance_nasdaq_client import (
        YahooFinanceNasdaqClient,
    )
    from app.domains.dashboard.adapter.outbound.persistence.nasdaq_repository_impl import (
        NasdaqRepositoryImpl,
    )
    from app.domains.dashboard.application.usecase.collect_nasdaq_bars_usecase import (
        CollectNasdaqBarsUseCase,
    )

    start = time.monotonic()
    logger.info("[Bootstrap][Nasdaq] 테이블 상태 확인 중...")
    async with AsyncSessionLocal() as db:
        repository = NasdaqRepositoryImpl(db)
        latest_date = await repository.find_latest_bar_date()

    if latest_date is not None:
        logger.info("[Bootstrap][Nasdaq] 데이터 존재 (latest=%s) — 부트스트랩 건너뜀", latest_date)
        return

    logger.info("[Bootstrap][Nasdaq] 데이터 없음 — 전체 데이터 수집 시작 (period=max)")
    async with AsyncSessionLocal() as db:
        usecase = CollectNasdaqBarsUseCase(
            yahoo_finance_port=YahooFinanceNasdaqClient(),
            nasdaq_repository=NasdaqRepositoryImpl(db),
        )
        saved = await usecase.execute(period="max")

    elapsed = time.monotonic() - start
    logger.info("[Bootstrap][Nasdaq] 완료 — saved=%d (%.1fs)", saved, elapsed)


async def job_collect_nasdaq_bars():
    """Daily KST 07:00 — 미국 장마감 후 나스닥 일봉 데이터를 yfinance에서 수집해 DB에 upsert한다.

    period="5d"로 최근 5 영업일을 수집해 누락·재처리를 허용한다.
    """
    from app.domains.dashboard.adapter.outbound.external.yahoo_finance_nasdaq_client import (
        YahooFinanceNasdaqClient,
    )
    from app.domains.dashboard.adapter.outbound.persistence.nasdaq_repository_impl import (
        NasdaqRepositoryImpl,
    )
    from app.domains.dashboard.application.usecase.collect_nasdaq_bars_usecase import (
        CollectNasdaqBarsUseCase,
    )

    start = time.monotonic()
    logger.info("[Scheduler][CollectNasdaq] 나스닥 일봉 수집 시작 (period=5d)")
    try:
        async with AsyncSessionLocal() as db:
            usecase = CollectNasdaqBarsUseCase(
                yahoo_finance_port=YahooFinanceNasdaqClient(),
                nasdaq_repository=NasdaqRepositoryImpl(db),
            )
            saved = await usecase.execute(period="5d")
            elapsed = time.monotonic() - start
            logger.info(
                "[Scheduler][CollectNasdaq] 완료 — saved=%d (%.1fs)", saved, elapsed
            )
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.error(
            "[Scheduler][CollectNasdaq] 실패 (%.1fs): %s", elapsed, str(e)
        )
