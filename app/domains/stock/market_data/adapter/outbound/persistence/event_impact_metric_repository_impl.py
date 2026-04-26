import logging
from datetime import date
from typing import List, Tuple

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.stock.market_data.application.port.out.event_impact_metric_repository_port import (
    EventImpactMetricRepositoryPort,
)
from app.domains.stock.market_data.domain.entity.event_impact_metric import (
    EventImpactMetric,
)
from app.domains.stock.market_data.infrastructure.mapper.event_impact_metric_mapper import (
    EventImpactMetricMapper,
)
from app.domains.stock.market_data.infrastructure.orm.event_impact_metric_orm import (
    EventImpactMetricOrm,
)

logger = logging.getLogger(__name__)


class EventImpactMetricRepositoryImpl(EventImpactMetricRepositoryPort):

    def __init__(self, db: AsyncSession):
        self._db = db

    async def upsert_bulk(self, metrics: List[EventImpactMetric]) -> int:
        if not metrics:
            return 0

        values = [
            {
                "ticker": m.ticker,
                "event_date": m.event_date,
                "event_type": m.event_type,
                "detail_hash": m.detail_hash,
                "benchmark_ticker": m.benchmark_ticker,
                "pre_days": m.pre_days,
                "post_days": m.post_days,
                "status": m.status,
                "cumulative_return_pct": m.cumulative_return_pct,
                "benchmark_return_pct": m.benchmark_return_pct,
                "abnormal_return_pct": m.abnormal_return_pct,
                "sample_completeness": m.sample_completeness,
                "bars_data_version": m.bars_data_version,
            }
            for m in metrics
        ]

        excluded = pg_insert(EventImpactMetricOrm).excluded
        stmt = (
            pg_insert(EventImpactMetricOrm)
            .values(values)
            .on_conflict_do_update(
                constraint="uq_event_impact_metrics_key",
                set_={
                    "benchmark_ticker": excluded.benchmark_ticker,
                    "status": excluded.status,
                    "cumulative_return_pct": excluded.cumulative_return_pct,
                    "benchmark_return_pct": excluded.benchmark_return_pct,
                    "abnormal_return_pct": excluded.abnormal_return_pct,
                    "sample_completeness": excluded.sample_completeness,
                    "bars_data_version": excluded.bars_data_version,
                    "computed_at": excluded.computed_at,
                },
            )
            .returning(EventImpactMetricOrm.id)
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        saved = len(result.fetchall())
        logger.info("[EventImpactMetricRepository] upsert 완료: %d rows", saved)
        return saved

    async def find_by_event_keys(
        self,
        keys: List[Tuple[str, date, str, str]],
    ) -> List[EventImpactMetric]:
        if not keys:
            return []
        stmt = select(EventImpactMetricOrm).where(
            tuple_(
                EventImpactMetricOrm.ticker,
                EventImpactMetricOrm.event_date,
                EventImpactMetricOrm.event_type,
                EventImpactMetricOrm.detail_hash,
            ).in_(keys)
        )
        result = await self._db.execute(stmt)
        return [
            EventImpactMetricMapper.to_entity(orm)
            for orm in result.scalars().all()
        ]
