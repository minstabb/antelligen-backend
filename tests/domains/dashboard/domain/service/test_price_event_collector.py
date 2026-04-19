"""
PriceEventCollector 단위 테스트 — 삼성전자(005930.KS) 1년치 수준의 합성 데이터 기준.

각 감지 로직을 독립적으로 검증한다.
"""
from datetime import date, timedelta
from typing import List

import pytest

from app.domains.dashboard.domain.entity.price_event import PriceEventType
from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.dashboard.domain.service.price_event_collector import PriceEventCollector


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def make_bar(
    days_ago: int,
    close: float,
    open_: float | None = None,
    volume: float = 1_000_000,
    high: float | None = None,
    low: float | None = None,
) -> StockBar:
    return StockBar(
        bar_date=date.today() - timedelta(days=days_ago),
        open=open_ if open_ is not None else close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=volume,
    )


def flat_bars(n: int, close: float = 100.0, volume: float = 1_000_000) -> List[StockBar]:
    """n개의 동일 가격/거래량 일봉 생성 (날짜 오름차순)."""
    return [make_bar(days_ago=n - i, close=close, volume=volume) for i in range(n)]


# ── 52주 신고가 / 신저가 ──────────────────────────────────────────────────────

class TestDetect52W:
    def test_high_52w_detected(self):
        bars = flat_bars(253, close=100.0)
        bars[-1] = make_bar(days_ago=0, close=101.0)  # 직전 252일 최고(100) 초과

        collector = PriceEventCollector()
        events = collector.collect(bars)
        types = [e.type for e in events]

        assert PriceEventType.HIGH_52W in types

    def test_low_52w_detected(self):
        bars = flat_bars(253, close=100.0)
        bars[-1] = make_bar(days_ago=0, close=99.0)  # 직전 252일 최저(100) 하회

        events = PriceEventCollector().collect(bars)
        assert any(e.type == PriceEventType.LOW_52W for e in events)

    def test_no_52w_event_when_within_range(self):
        bars = flat_bars(253, close=100.0)  # 전부 동일 → 신고가/신저가 없음

        events = PriceEventCollector().collect(bars)
        types = [e.type for e in events]

        assert PriceEventType.HIGH_52W not in types
        assert PriceEventType.LOW_52W not in types

    def test_52w_requires_252_day_window(self):
        """252일 미만 데이터에서는 52주 이벤트가 발생하지 않아야 한다."""
        bars = flat_bars(251, close=100.0)
        bars[-1] = make_bar(days_ago=0, close=200.0)

        events = PriceEventCollector().collect(bars)
        assert all(e.type not in (PriceEventType.HIGH_52W, PriceEventType.LOW_52W) for e in events)


# ── ±5% 등락 ─────────────────────────────────────────────────────────────────

class TestDetectPriceChange:
    def test_surge_detected(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=106.0),  # +6%
        ]
        events = PriceEventCollector().collect(bars)
        assert any(e.type == PriceEventType.SURGE for e in events)

    def test_plunge_detected(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=94.0),  # -6%
        ]
        events = PriceEventCollector().collect(bars)
        assert any(e.type == PriceEventType.PLUNGE for e in events)

    def test_no_event_below_threshold(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=103.0),  # +3% → 임계값 미만
        ]
        events = PriceEventCollector().collect(bars)
        assert all(e.type not in (PriceEventType.SURGE, PriceEventType.PLUNGE) for e in events)

    def test_surge_value_is_correct(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=110.0),  # +10%
        ]
        events = PriceEventCollector().collect(bars)
        surge = next(e for e in events if e.type == PriceEventType.SURGE)
        assert abs(surge.value - 10.0) < 0.01


# ── 갭 상승 / 하락 ────────────────────────────────────────────────────────────

class TestDetectGap:
    def test_gap_up_detected(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=103.0, open_=103.0),  # 갭 +3%
        ]
        events = PriceEventCollector().collect(bars)
        assert any(e.type == PriceEventType.GAP_UP for e in events)

    def test_gap_down_detected(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=97.0, open_=97.0),  # 갭 -3%
        ]
        events = PriceEventCollector().collect(bars)
        assert any(e.type == PriceEventType.GAP_DOWN for e in events)

    def test_no_gap_below_threshold(self):
        bars = [
            make_bar(days_ago=1, close=100.0),
            make_bar(days_ago=0, close=101.0, open_=101.0),  # +1% → 임계값 미만
        ]
        events = PriceEventCollector().collect(bars)
        assert all(e.type not in (PriceEventType.GAP_UP, PriceEventType.GAP_DOWN) for e in events)


# ── 통합 ─────────────────────────────────────────────────────────────────────

class TestCollectIntegration:
    def test_empty_bars_returns_empty(self):
        assert PriceEventCollector().collect([]) == []

    def test_single_bar_returns_empty(self):
        assert PriceEventCollector().collect([make_bar(0, 100.0)]) == []

    def test_events_sorted_by_date(self):
        bars = flat_bars(253, close=100.0)
        bars[1] = make_bar(days_ago=252, close=94.0)   # PLUNGE 발생 (앞)
        bars[-1] = make_bar(days_ago=0, close=107.0)   # SURGE 발생 (뒤)

        events = PriceEventCollector().collect(bars)
        dates = [e.date for e in events]
        assert dates == sorted(dates)

    def test_multiple_event_types_on_same_day(self):
        """같은 날 갭 상승 + 급등이 동시에 발생할 수 있다."""
        bars = flat_bars(20, close=100.0, volume=1_000_000)
        # 급등(+10%) + 갭(+10%) + 거래량 5배 동시 발생
        bars.append(make_bar(days_ago=0, close=110.0, open_=110.0, volume=5_000_000))

        events = PriceEventCollector().collect(bars)
        event_types = {e.type for e in events}

        assert PriceEventType.SURGE in event_types
        assert PriceEventType.GAP_UP in event_types
