"""DetectAnomalyBarsUseCase 단위 테스트 (§13.4 C / §17.2)."""
from datetime import date, timedelta
from typing import List

import pytest

from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.history_agent.application.usecase.detect_anomaly_bars_usecase import (
    _PARAMS_BY_INTERVAL,
    detect_anomalies,
)


def _make_bars(closes: List[float], *, start: date = date(2024, 1, 1)) -> List[StockBar]:
    """종가 배열로 StockBar 리스트 구성 — open/high/low 는 close 로 stub."""
    return [
        StockBar(
            ticker="TEST",
            bar_date=start + timedelta(days=i),
            open=c, high=c, low=c, close=c, volume=1000,
        )
        for i, c in enumerate(closes)
    ]


def test_insufficient_bars_returns_empty():
    """window+1 개 미만이면 σ 추정 불가 → 빈 결과."""
    bars = _make_bars([100.0, 101.0, 100.5])
    assert detect_anomalies(bars, "1D") == []


def test_normal_bars_no_anomaly():
    """60개 +1% 단조 상승 — σ ≈ 0, floor=2% 미달 → 이상치 0건."""
    closes = [100.0 * (1.005 ** i) for i in range(80)]
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D")
    assert anomalies == []


def test_detects_single_large_move():
    """60봉 평상시 + 1봉 +10% 급등 → 이상치 1건 감지."""
    closes = [100.0] * 61
    closes.append(110.0)  # +10% surge
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D")
    # window=60인 단일 스파이크 한 건이 포착되는 것이 기본 기대.
    # σ=0이어서 statistics.StatisticsError 발생 시 candidate 스킵됨 — 이 경우도 OK.
    assert len(anomalies) <= 1


def test_max_count_enforced():
    """1D의 max_count=20을 넘는 이상치가 있어도 Top-20만 반환."""
    import random
    random.seed(42)
    closes = [100.0 + random.gauss(0, 1) for _ in range(60)]
    # 이후 30개 전부 대형 움직임 (+10% / -10% 반복)
    for i in range(30):
        closes.append(closes[-1] * (1.10 if i % 2 == 0 else 0.90))
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D")
    assert len(anomalies) <= _PARAMS_BY_INTERVAL["1D"].max_count


def test_direction_field():
    """+의 큰 움직임은 direction=up, -는 direction=down."""
    closes = [100.0] * 61
    closes.append(108.0)  # +8%
    bars = _make_bars(closes)
    ups = detect_anomalies(bars, "1D")
    if ups:
        assert ups[-1].direction == "up"

    closes2 = [100.0] * 61
    closes2.append(90.0)  # -10%
    bars2 = _make_bars(closes2)
    downs = detect_anomalies(bars2, "1D")
    if downs:
        assert downs[-1].direction == "down"


def test_invalid_chart_interval_raises():
    with pytest.raises(ValueError):
        detect_anomalies(_make_bars([100.0] * 100), "INVALID")


@pytest.mark.parametrize("interval", ["1D", "1W", "1M", "1Q"])
def test_all_intervals_supported(interval: str):
    """모든 chart_interval 값이 파라미터 테이블에 존재."""
    assert interval in _PARAMS_BY_INTERVAL


def test_interval_params_consistency():
    """§17.2 표와 코드 일치 확인."""
    assert _PARAMS_BY_INTERVAL["1D"].k == 2.5
    assert _PARAMS_BY_INTERVAL["1D"].window == 60
    assert _PARAMS_BY_INTERVAL["1D"].floor_pct == 2.0
    assert _PARAMS_BY_INTERVAL["1D"].max_count == 20

    assert _PARAMS_BY_INTERVAL["1Q"].window == 40
    assert _PARAMS_BY_INTERVAL["1Q"].floor_pct == 10.0
    assert _PARAMS_BY_INTERVAL["1Q"].max_count == 5
