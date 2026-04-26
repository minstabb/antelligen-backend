from datetime import date, datetime

from app.domains.stock.market_data.infrastructure.mapper.event_impact_metric_mapper import (
    EventImpactMetricMapper,
)
from app.domains.stock.market_data.infrastructure.orm.event_impact_metric_orm import (
    EventImpactMetricOrm,
)


def test_to_entity_preserves_all_fields():
    orm = EventImpactMetricOrm(
        id=99,
        ticker="AAPL",
        event_date=date(2026, 3, 15),
        event_type="CRISIS",
        detail_hash="deadbeefcafebabe",
        benchmark_ticker="^GSPC",
        pre_days=-1,
        post_days=5,
        status="OK",
        cumulative_return_pct=5.2,
        benchmark_return_pct=2.1,
        abnormal_return_pct=3.1,
        sample_completeness=1.0,
        bars_data_version="yfinance:adjusted:2026-04-26",
        computed_at=datetime(2026, 4, 27, 8, 0, 0),
    )

    entity = EventImpactMetricMapper.to_entity(orm)

    assert entity.id == 99
    assert entity.ticker == "AAPL"
    assert entity.event_date == date(2026, 3, 15)
    assert entity.benchmark_ticker == "^GSPC"
    assert entity.pre_days == -1
    assert entity.post_days == 5
    assert entity.status == "OK"
    assert entity.abnormal_return_pct == 3.1
    assert entity.bars_data_version == "yfinance:adjusted:2026-04-26"
