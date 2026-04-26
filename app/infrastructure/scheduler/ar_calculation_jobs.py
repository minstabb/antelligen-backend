"""Abnormal return 계산 잡 (PR2).

매일 KST 08:00 — daily_bars 적재 잡(07:30) 이 끝난 후 실행. event_date <= today - 21d
조건으로 ±20거래일 후속 데이터 가용성 확보.
"""
import logging
import time
from datetime import date, timedelta

from app.infrastructure.database.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# 사용자 분류 원칙: 시점 명확 사건 카테고리만 AR 계산 대상.
_TARGET_EVENT_TYPES = [
    # CORPORATE
    "STOCK_SPLIT",
    "MERGER_ACQUISITION",
    "BUYBACK",
    "SPINOFF",
    # ANNOUNCEMENT
    "MANAGEMENT_CHANGE",
    "ACCOUNTING_ISSUE",
    "REGULATORY",
    "PRODUCT_LAUNCH",
    "CRISIS",
    "ARTICLES_AMENDMENT",
    "DISCLOSURE",
    "MAJOR_EVENT",
    "CONTRACT",
    # MACRO 의 시점 명확 사건 (curated 카탈로그 + 서프라이즈)
    "CRISIS_EVENT",
    "GEOPOLITICAL_RISK",
]

_BUSINESS_DAYS_FOR_FULL_WINDOW = 21


async def job_calculate_abnormal_returns_daily():
    """daily KST 08:00 — AR 미계산 이벤트 배치 처리."""
    from app.domains.dashboard.adapter.outbound.external.cached_asset_type_adapter import (
        CachedAssetTypeAdapter,
    )
    from app.domains.dashboard.adapter.outbound.external.yahoo_finance_asset_type_client import (
        YahooFinanceAssetTypeClient,
    )
    from app.domains.stock.market_data.adapter.outbound.persistence.daily_bar_repository_impl import (
        DailyBarRepositoryImpl,
    )
    from app.domains.stock.market_data.adapter.outbound.persistence.event_impact_metric_repository_impl import (
        EventImpactMetricRepositoryImpl,
    )
    from app.domains.stock.market_data.adapter.outbound.persistence.pending_event_for_impact_query_impl import (
        PendingEventForImpactQueryImpl,
    )
    from app.domains.stock.market_data.application.usecase.compute_event_impact_usecase import (
        ComputeEventImpactUseCase,
    )
    from app.infrastructure.cache.redis_client import redis_client

    start = time.monotonic()
    cutoff = date.today() - timedelta(days=_BUSINESS_DAYS_FOR_FULL_WINDOW)
    logger.info(
        "[Scheduler][ComputeEventImpact] 시작 (cutoff=%s, types=%d)",
        cutoff, len(_TARGET_EVENT_TYPES),
    )

    try:
        async with AsyncSessionLocal() as db:
            usecase = ComputeEventImpactUseCase(
                pending_query=PendingEventForImpactQueryImpl(db),
                daily_bar_repository=DailyBarRepositoryImpl(db),
                impact_repository=EventImpactMetricRepositoryImpl(db),
                asset_type_port=CachedAssetTypeAdapter(
                    YahooFinanceAssetTypeClient(), redis_client
                ),
            )
            saved = await usecase.execute(
                cutoff_date=cutoff,
                event_types=_TARGET_EVENT_TYPES,
                limit=2000,
            )
        elapsed = time.monotonic() - start
        logger.info(
            "[Scheduler][ComputeEventImpact] 완료 — saved=%d (%.1fs)",
            saved, elapsed,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - start
        logger.error(
            "[Scheduler][ComputeEventImpact] 실패 (%.1fs): %s", elapsed, exc
        )
