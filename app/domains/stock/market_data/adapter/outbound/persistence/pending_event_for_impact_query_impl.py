"""PendingEventForImpactQueryPort 구현 — event_enrichments × event_impact_metrics LEFT JOIN.

cross-domain ORM 참조: history_agent.event_enrichment_orm 을 read-side 만 import.
write-side는 history_agent 가 단독 소유 유지.
"""
from datetime import date
from typing import List

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.history_agent.infrastructure.orm.event_enrichment_orm import (
    EventEnrichmentOrm,
)
from app.domains.stock.market_data.application.port.out.pending_event_for_impact_query_port import (
    PendingEventForImpact,
    PendingEventForImpactQueryPort,
)
from app.domains.stock.market_data.infrastructure.orm.event_impact_metric_orm import (
    EventImpactMetricOrm,
)


class PendingEventForImpactQueryImpl(PendingEventForImpactQueryPort):

    def __init__(self, db: AsyncSession):
        self._db = db

    async def find_pending(
        self,
        cutoff_date: date,
        event_types: List[str],
        limit: int = 1000,
    ) -> List[PendingEventForImpact]:
        # 한 enrichment 행에 대해 (pre_days=-1, post_days=5) 와 (pre_days=-1, post_days=20)
        # 두 윈도우를 모두 계산해 저장하므로 metric COUNT가 2 미만이면 pending.
        impact_count = (
            select(
                EventImpactMetricOrm.ticker.label("ticker"),
                EventImpactMetricOrm.event_date.label("event_date"),
                EventImpactMetricOrm.event_type.label("event_type"),
                EventImpactMetricOrm.detail_hash.label("detail_hash"),
                func.count(EventImpactMetricOrm.id).label("metric_count"),
            )
            .group_by(
                EventImpactMetricOrm.ticker,
                EventImpactMetricOrm.event_date,
                EventImpactMetricOrm.event_type,
                EventImpactMetricOrm.detail_hash,
            )
            .subquery()
        )

        stmt = (
            select(
                EventEnrichmentOrm.ticker,
                EventEnrichmentOrm.event_date,
                EventEnrichmentOrm.event_type,
                EventEnrichmentOrm.detail_hash,
            )
            .distinct()
            .outerjoin(
                impact_count,
                and_(
                    impact_count.c.ticker == EventEnrichmentOrm.ticker,
                    impact_count.c.event_date == EventEnrichmentOrm.event_date,
                    impact_count.c.event_type == EventEnrichmentOrm.event_type,
                    impact_count.c.detail_hash == EventEnrichmentOrm.detail_hash,
                ),
            )
            .where(
                EventEnrichmentOrm.event_date <= cutoff_date,
                EventEnrichmentOrm.event_type.in_(event_types),
                # NULL = 한 번도 계산 안 됨, < 2 = 일부 윈도우만 계산됨
                (impact_count.c.metric_count.is_(None))
                | (impact_count.c.metric_count < 2),
            )
            .order_by(EventEnrichmentOrm.event_date.desc())
            .limit(limit)
        )

        result = await self._db.execute(stmt)
        return [
            PendingEventForImpact(
                ticker=ticker,
                event_date=event_date,
                event_type=event_type,
                detail_hash=detail_hash,
            )
            for ticker, event_date, event_type, detail_hash in result.all()
        ]
