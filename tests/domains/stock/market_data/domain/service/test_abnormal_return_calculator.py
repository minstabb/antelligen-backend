from datetime import date, timedelta
from typing import List

import pytest

from app.domains.stock.market_data.domain.entity.daily_bar import DailyBar
from app.domains.stock.market_data.domain.service.abnormal_return_calculator import (
    AbnormalReturnCalculator,
)
from app.domains.stock.market_data.domain.value_object.event_impact_status import (
    EventImpactStatus,
)


def _bar(d: date, close: float, ticker: str = "TEST") -> DailyBar:
    return DailyBar(
        ticker=ticker,
        bar_date=d,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
    )


def _series(start: date, closes: List[float], ticker: str = "TEST") -> List[DailyBar]:
    return [_bar(start + timedelta(days=i), c, ticker) for i, c in enumerate(closes)]


def test_golden_case_stock_outperforms_benchmark_5pct():
    """종목 +5%, 벤치 +2% → AR = +3%."""
    # event 직전 종가 100, 5거래일 후 종가 105 = +5%
    stock = _series(date(2026, 4, 1), [100.0, 100.5, 101.0, 102.0, 103.0, 104.0, 105.0])
    bench = _series(date(2026, 4, 1), [200.0, 200.0, 201.0, 202.0, 202.5, 203.5, 204.0])
    # event_date = 2026-04-02 → 직전(t-1) = 2026-04-01 close
    # post +5거래일 = 2026-04-07 close (인덱스 6)
    result = AbnormalReturnCalculator.compute(
        stock_bars=stock,
        benchmark_bars=bench,
        event_date=date(2026, 4, 2),
        post_days=5,
    )
    assert result.status == EventImpactStatus.OK
    # stock: 100 → 105 = +5.0%
    # bench: 200 → 204 = +2.0%
    # ar = +3.0%
    assert result.cumulative_return_pct == pytest.approx(5.0, abs=0.01)
    assert result.benchmark_return_pct == pytest.approx(2.0, abs=0.01)
    assert result.abnormal_return_pct == pytest.approx(3.0, abs=0.01)
    assert result.sample_completeness == 1.0


def test_event_on_non_trading_day_uses_next_trading_day():
    """이벤트 날짜 자체가 bars 에 없는 경우 그 다음 거래일을 t0 로 처리."""
    # 2026-04-04(토) 공시. 직전 거래일 종가 = 2026-04-03 close.
    stock = _series(date(2026, 4, 1), [100.0, 100.0, 100.0, 105.0, 105.0])
    bench = _series(date(2026, 4, 1), [200.0, 200.0, 200.0, 210.0, 210.0])
    # event_date = 2026-04-04 (토). pre = 2026-04-03 close. post +1 = 2026-04-05.
    result = AbnormalReturnCalculator.compute(
        stock_bars=stock,
        benchmark_bars=bench,
        event_date=date(2026, 4, 4),
        post_days=1,
    )
    assert result.status == EventImpactStatus.OK


def test_insufficient_data_when_post_window_too_short():
    """post_days 이후 거래일 부족 시 INSUFFICIENT_DATA."""
    stock = _series(date(2026, 4, 1), [100.0, 102.0])  # 2 거래일만
    bench = _series(date(2026, 4, 1), [200.0, 200.0])
    result = AbnormalReturnCalculator.compute(
        stock_bars=stock,
        benchmark_bars=bench,
        event_date=date(2026, 4, 2),
        post_days=20,  # 20거래일 후 종가 부재
    )
    assert result.status == EventImpactStatus.INSUFFICIENT_DATA


def test_no_pre_close_returns_insufficient():
    """이벤트일 이전 거래일 종가 부재."""
    # event = 2026-04-01, bars 는 그날부터 시작 — 직전 거래일 종가 없음
    stock = _series(date(2026, 4, 1), [100.0, 105.0, 110.0])
    bench = _series(date(2026, 4, 1), [200.0, 205.0, 210.0])
    result = AbnormalReturnCalculator.compute(
        stock_bars=stock,
        benchmark_bars=bench,
        event_date=date(2026, 4, 1),
        post_days=1,
    )
    assert result.status == EventImpactStatus.INSUFFICIENT_DATA


def test_empty_stock_bars_returns_stock_data_missing():
    bench = _series(date(2026, 4, 1), [200.0, 205.0])
    result = AbnormalReturnCalculator.compute(
        stock_bars=[],
        benchmark_bars=bench,
        event_date=date(2026, 4, 1),
        post_days=1,
    )
    assert result.status == EventImpactStatus.STOCK_DATA_MISSING


def test_empty_benchmark_bars_returns_benchmark_data_missing():
    stock = _series(date(2026, 4, 1), [100.0, 105.0])
    result = AbnormalReturnCalculator.compute(
        stock_bars=stock,
        benchmark_bars=[],
        event_date=date(2026, 4, 1),
        post_days=1,
    )
    assert result.status == EventImpactStatus.BENCHMARK_DATA_MISSING


def test_post_days_must_be_positive():
    with pytest.raises(ValueError):
        AbnormalReturnCalculator.compute(
            stock_bars=[],
            benchmark_bars=[],
            event_date=date(2026, 4, 1),
            post_days=0,
        )


def test_negative_abnormal_return_when_stock_underperforms():
    """종목이 벤치보다 부진 → AR 음수."""
    stock = _series(date(2026, 4, 1), [100.0, 100.0, 95.0])  # -5%
    bench = _series(date(2026, 4, 1), [200.0, 200.0, 204.0])  # +2%
    result = AbnormalReturnCalculator.compute(
        stock_bars=stock,
        benchmark_bars=bench,
        event_date=date(2026, 4, 2),
        post_days=1,
    )
    assert result.status == EventImpactStatus.OK
    assert result.abnormal_return_pct == pytest.approx(-7.0, abs=0.01)
