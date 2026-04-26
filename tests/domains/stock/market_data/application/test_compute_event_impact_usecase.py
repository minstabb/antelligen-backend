import asyncio
from datetime import date, timedelta
from typing import List

from app.domains.dashboard.application.port.out.asset_type_port import AssetTypePort
from app.domains.stock.market_data.application.port.out.daily_bar_repository_port import (
    DailyBarRepositoryPort,
)
from app.domains.stock.market_data.application.port.out.event_impact_metric_repository_port import (
    EventImpactMetricRepositoryPort,
)
from app.domains.stock.market_data.application.port.out.pending_event_for_impact_query_port import (
    PendingEventForImpact,
    PendingEventForImpactQueryPort,
)
from app.domains.stock.market_data.application.usecase.compute_event_impact_usecase import (
    ComputeEventImpactUseCase,
)
from app.domains.stock.market_data.domain.entity.daily_bar import DailyBar
from app.domains.stock.market_data.domain.entity.event_impact_metric import (
    EventImpactMetric,
)
from app.domains.stock.market_data.domain.value_object.event_impact_status import (
    EventImpactStatus,
)


class _StubPendingQuery(PendingEventForImpactQueryPort):
    def __init__(self, pending: List[PendingEventForImpact]):
        self._pending = pending

    async def find_pending(self, cutoff_date, event_types, limit=1000):
        return list(self._pending)


class _StubDailyBarRepo(DailyBarRepositoryPort):
    def __init__(self, by_ticker: dict[str, List[DailyBar]]):
        self._by_ticker = by_ticker

    async def upsert_bulk(self, bars):
        return 0

    async def find_range(self, ticker, start, end):
        bars = self._by_ticker.get(ticker, [])
        return [b for b in bars if start <= b.bar_date <= end]

    async def find_around(self, ticker, event_date, before_days, after_days):
        bars = self._by_ticker.get(ticker, [])
        start = event_date - timedelta(days=before_days)
        end = event_date + timedelta(days=after_days)
        return [b for b in bars if start <= b.bar_date <= end]

    async def find_latest_bar_date(self, ticker):
        bars = self._by_ticker.get(ticker, [])
        return max((b.bar_date for b in bars), default=None)

    async def find_distinct_tickers(self):
        return list(self._by_ticker.keys())


class _StubImpactRepo(EventImpactMetricRepositoryPort):
    def __init__(self):
        self.upserted: List[EventImpactMetric] = []

    async def upsert_bulk(self, metrics):
        self.upserted.extend(metrics)
        return len(metrics)

    async def find_by_event_keys(self, keys):
        return []


class _StubAssetTypePort(AssetTypePort):
    def __init__(self, by_ticker: dict[str, str]):
        self._by_ticker = by_ticker

    async def get_quote_type(self, ticker):
        return self._by_ticker.get(ticker, "UNKNOWN")


def _bars(ticker: str, start: date, closes: List[float]) -> List[DailyBar]:
    return [
        DailyBar(
            ticker=ticker,
            bar_date=start + timedelta(days=i),
            open=c,
            high=c,
            low=c,
            close=c,
            volume=1000,
            bars_data_version="yfinance:adjusted:2026-04-26",
        )
        for i, c in enumerate(closes)
    ]


def _pending(ticker: str, event_date: date) -> PendingEventForImpact:
    return PendingEventForImpact(
        ticker=ticker,
        event_date=event_date,
        event_type="CRISIS",
        detail_hash="abc123",
    )


def test_empty_pending_returns_zero():
    usecase = ComputeEventImpactUseCase(
        pending_query=_StubPendingQuery([]),
        daily_bar_repository=_StubDailyBarRepo({}),
        impact_repository=_StubImpactRepo(),
        asset_type_port=_StubAssetTypePort({}),
    )
    saved = asyncio.run(
        usecase.execute(cutoff_date=date(2026, 4, 1), event_types=["CRISIS"])
    )
    assert saved == 0


def test_us_equity_creates_2_metrics_per_event_5d_and_20d():
    """OK 케이스 — 한 이벤트당 5d/20d 두 윈도우 metric 저장."""
    start = date(2026, 4, 1)
    # 30일 data — 거래일은 모두 +1% 균일 상승하는 종목과 +0.5% 벤치
    stock_closes = [100.0 * (1.01 ** i) for i in range(30)]
    bench_closes = [200.0 * (1.005 ** i) for i in range(30)]

    repo = _StubImpactRepo()
    usecase = ComputeEventImpactUseCase(
        pending_query=_StubPendingQuery([_pending("AAPL", date(2026, 4, 5))]),
        daily_bar_repository=_StubDailyBarRepo(
            {
                "AAPL": _bars("AAPL", start, stock_closes),
                "^GSPC": _bars("^GSPC", start, bench_closes),
            }
        ),
        impact_repository=repo,
        asset_type_port=_StubAssetTypePort({"AAPL": "EQUITY"}),
    )
    saved = asyncio.run(
        usecase.execute(cutoff_date=date(2026, 4, 30), event_types=["CRISIS"])
    )
    assert saved == 2  # 5d + 20d
    assert all(m.benchmark_ticker == "^GSPC" for m in repo.upserted)
    assert sorted(m.post_days for m in repo.upserted) == [5, 20]
    assert all(m.status == EventImpactStatus.OK.value for m in repo.upserted)
    assert all(m.bars_data_version is not None for m in repo.upserted)
    # AR 부호: 종목 > 벤치이므로 양수
    assert all(m.abnormal_return_pct > 0 for m in repo.upserted)


def test_etf_skips_with_benchmark_missing_status():
    """비-EQUITY 도 행을 저장 — 다음 실행에서 재계산 방지."""
    repo = _StubImpactRepo()
    usecase = ComputeEventImpactUseCase(
        pending_query=_StubPendingQuery([_pending("SPY", date(2026, 4, 5))]),
        daily_bar_repository=_StubDailyBarRepo({}),
        impact_repository=repo,
        asset_type_port=_StubAssetTypePort({"SPY": "ETF"}),
    )
    saved = asyncio.run(
        usecase.execute(cutoff_date=date(2026, 4, 30), event_types=["CRISIS"])
    )
    assert saved == 2  # 두 윈도우 모두 BENCHMARK_MISSING 으로 저장
    assert all(
        m.status == EventImpactStatus.BENCHMARK_MISSING.value for m in repo.upserted
    )
    assert all(m.benchmark_ticker == "" for m in repo.upserted)


def test_missing_stock_bars_marks_data_missing():
    """daily_bars 미적재 ticker → STOCK_DATA_MISSING."""
    repo = _StubImpactRepo()
    usecase = ComputeEventImpactUseCase(
        pending_query=_StubPendingQuery([_pending("NVDA", date(2026, 4, 5))]),
        daily_bar_repository=_StubDailyBarRepo({}),  # bars 없음
        impact_repository=repo,
        asset_type_port=_StubAssetTypePort({"NVDA": "EQUITY"}),
    )
    saved = asyncio.run(
        usecase.execute(cutoff_date=date(2026, 4, 30), event_types=["CRISIS"])
    )
    assert saved == 2
    assert all(
        m.status == EventImpactStatus.STOCK_DATA_MISSING.value for m in repo.upserted
    )


def test_groups_events_by_ticker_for_efficient_processing():
    """같은 ticker 의 여러 이벤트는 그룹으로 처리되어 metric 수가 (events × 2)."""
    repo = _StubImpactRepo()
    start = date(2026, 4, 1)
    closes = [100.0 + i for i in range(30)]
    usecase = ComputeEventImpactUseCase(
        pending_query=_StubPendingQuery([
            _pending("AAPL", date(2026, 4, 5)),
            _pending("AAPL", date(2026, 4, 10)),
            _pending("AAPL", date(2026, 4, 15)),
        ]),
        daily_bar_repository=_StubDailyBarRepo({
            "AAPL": _bars("AAPL", start, closes),
            "^GSPC": _bars("^GSPC", start, closes),
        }),
        impact_repository=repo,
        asset_type_port=_StubAssetTypePort({"AAPL": "EQUITY"}),
    )
    saved = asyncio.run(
        usecase.execute(cutoff_date=date(2026, 4, 30), event_types=["CRISIS"])
    )
    assert saved == 6  # 3 events × 2 windows
