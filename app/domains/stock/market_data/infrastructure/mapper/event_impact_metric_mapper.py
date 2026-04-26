from app.domains.stock.market_data.domain.entity.event_impact_metric import (
    EventImpactMetric,
)
from app.domains.stock.market_data.infrastructure.orm.event_impact_metric_orm import (
    EventImpactMetricOrm,
)


class EventImpactMetricMapper:

    @staticmethod
    def to_entity(orm: EventImpactMetricOrm) -> EventImpactMetric:
        return EventImpactMetric(
            id=orm.id,
            ticker=orm.ticker,
            event_date=orm.event_date,
            event_type=orm.event_type,
            detail_hash=orm.detail_hash,
            benchmark_ticker=orm.benchmark_ticker,
            pre_days=orm.pre_days,
            post_days=orm.post_days,
            status=orm.status,
            cumulative_return_pct=orm.cumulative_return_pct,
            benchmark_return_pct=orm.benchmark_return_pct,
            abnormal_return_pct=orm.abnormal_return_pct,
            sample_completeness=orm.sample_completeness,
            bars_data_version=orm.bars_data_version,
            computed_at=orm.computed_at,
        )
