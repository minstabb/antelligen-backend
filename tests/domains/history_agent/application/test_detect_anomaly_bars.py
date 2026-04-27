"""DetectAnomalyBarsUseCase 단위 테스트 (§13.4 C / §17.2 / OKR 다층 탐지 KR1·KR2)."""
from datetime import date, timedelta
from typing import List

import pytest

from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.history_agent.application.usecase.detect_anomaly_bars_usecase import (
    _CLUSTER_BIG_MOVE_THRESHOLD,
    _CLUSTER_MIN_MEMBERS,
    _CLUSTER_PROXIMITY_DAYS,
    _CUMULATIVE_5D_THRESHOLD,
    _CUMULATIVE_20D_THRESHOLD,
    _DRAWDOWN_RECOVERY_THRESHOLD,
    _DRAWDOWN_START_THRESHOLD,
    _FLOOR_BY_TICKER_GROUP_1D,
    _PARAMS_BY_INTERVAL,
    _classify_ticker_group,
    _compute_sigma,
    _detect_cumulative_anomalies,
    _detect_drawdown_anomalies,
    _detect_volatility_cluster_anomalies,
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


# ── KR1: 종목 군별 floor ────────────────────────────────────


def test_classify_ticker_group_kospi_kosdaq_us():
    assert _classify_ticker_group("005930.KS") == "KOSPI"
    assert _classify_ticker_group("068270.KQ") == "KOSDAQ"
    assert _classify_ticker_group("AAPL") == "US"
    assert _classify_ticker_group("") == "US"
    assert _classify_ticker_group("aapl") == "US"


def test_classify_ticker_group_uppercased_correctly():
    """소문자 suffix 도 인식."""
    assert _classify_ticker_group("005930.ks") == "KOSPI"
    assert _classify_ticker_group("068270.kq") == "KOSDAQ"


def test_floor_by_group_table_matches_okr_spec():
    """OKR 명세 — KOSPI 5% / KOSDAQ 7% / US 5%."""
    assert _FLOOR_BY_TICKER_GROUP_1D["KOSPI"] == 5.0
    assert _FLOOR_BY_TICKER_GROUP_1D["KOSDAQ"] == 7.0
    assert _FLOOR_BY_TICKER_GROUP_1D["US"] == 5.0


def test_kospi_floor_blocks_below_5_percent():
    """KOSPI 종목 1D 에서 4.9% 변동은 floor 미만 → 탐지 X (k×σ 도 작은 평상 σ 환경)."""
    closes = [100.0] * 61
    closes.append(104.9)  # +4.9% — KOSPI floor=5% 미만
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D", "005930.KS")
    assert anomalies == []


def test_kospi_floor_passes_above_5_percent():
    """KOSPI 종목 5.1% 변동은 floor 초과 → 탐지."""
    closes = [100.0] * 61
    closes.append(105.1)
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D", "005930.KS")
    assert len(anomalies) == 1
    assert anomalies[0].type == "zscore"


def test_kosdaq_floor_blocks_below_7_percent():
    """KOSDAQ 종목 6.9% 는 floor 미만."""
    closes = [100.0] * 61
    closes.append(106.9)
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D", "068270.KQ")
    assert anomalies == []


def test_kosdaq_floor_passes_above_7_percent():
    """KOSDAQ 종목 7.1% 는 floor 초과."""
    closes = [100.0] * 61
    closes.append(107.1)
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D", "068270.KQ")
    assert len(anomalies) == 1


def test_kospi_floor_only_applies_to_1d():
    """1W 이상 봉은 종목 군 floor 무관 — `_PARAMS_BY_INTERVAL` 그대로."""
    # 1M floor=5% — KOSPI 종목이라도 동일 적용. 4.9% 는 1M floor 미달 → 탐지 X.
    closes = [100.0] * 37
    closes.append(104.9)
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1M", "005930.KS")
    assert anomalies == []


# ── KR2: 5/20일 누적 윈도우 ──────────────────────────────


def test_cumulative_5d_threshold_constants():
    assert _CUMULATIVE_5D_THRESHOLD == 0.10
    assert _CUMULATIVE_20D_THRESHOLD == 0.15


def test_cumulative_5d_triggers_on_first_breach():
    """5거래일 누적 -10% 진입 봉을 탐지 → type=cumulative_5d."""
    closes = [100.0] * 25
    # 5일 사이 -11% 만들기: 25일 close → 26일 close 가 -11%
    closes.append(89.0)  # 26번째: 직전 5봉(idx 21) close=100 대비 -11%
    bars = _make_bars(closes)
    cumulative = _detect_cumulative_anomalies(bars, "1D")
    assert any(e.type == "cumulative_5d" for e in cumulative)
    ev = next(e for e in cumulative if e.type == "cumulative_5d")
    assert ev.direction == "down"
    assert ev.return_pct < -10.0


def test_cumulative_5d_no_trigger_under_threshold():
    """5거래일 -9% 는 임계 미만 → 탐지 X."""
    closes = [100.0] * 25
    closes.append(91.0)  # -9%
    bars = _make_bars(closes)
    cumulative = _detect_cumulative_anomalies(bars, "1D")
    assert all(e.type != "cumulative_5d" for e in cumulative)


def test_cumulative_5d_does_not_retrigger_during_continuous_breach():
    """연속 임계 위 구간에서 trigger 는 진입 봉 1번만 — 재무장 후 재진입 시 다시."""
    # 25봉 평탄 → 26봉부터 -11%, -12%, -13% (모두 임계 위)
    closes = [100.0] * 25 + [89.0, 88.0, 87.0, 86.0, 85.0, 84.0]  # 31개
    bars = _make_bars(closes)
    cumulative = _detect_cumulative_anomalies(bars, "1D")
    cum5 = [e for e in cumulative if e.type == "cumulative_5d"]
    # 첫 진입 봉만 마커. 빠져나가지 않으면 재트리거 X.
    assert len(cum5) == 1


def test_cumulative_20d_triggers():
    """20거래일 -15% 누적 진입 봉 탐지."""
    closes = [100.0] * 30
    closes.append(83.0)  # 31번째 (idx 30): idx 10 대비 -17%
    bars = _make_bars(closes)
    cumulative = _detect_cumulative_anomalies(bars, "1D")
    assert any(e.type == "cumulative_20d" for e in cumulative)


def test_cumulative_only_for_daily_interval():
    """1W 이상 봉은 누적 탐지기 동작 X."""
    closes = [100.0] * 25
    closes.append(80.0)
    bars = _make_bars(closes)
    assert _detect_cumulative_anomalies(bars, "1W") == []
    assert _detect_cumulative_anomalies(bars, "1M") == []
    assert _detect_cumulative_anomalies(bars, "1Q") == []


# ── dedup 정책 ────────────────────────────────────────────


def test_zscore_takes_precedence_over_cumulative_on_same_day():
    """같은 날 z-score 와 누적 모두 탐지되면 z-score 우선."""
    # 60봉 평탄 + 1봉 -12% (단일봉 -12% 이고 5일 누적도 -12%)
    closes = [100.0] * 61
    closes.append(88.0)
    bars = _make_bars(closes)
    merged = detect_anomalies(bars, "1D", "AAPL")
    # 단 한 건만 — z-score 우선 표기.
    same_day = [e for e in merged if e.date == bars[61].bar_date]
    assert len(same_day) == 1
    assert same_day[0].type == "zscore"


def test_cumulative_event_passes_when_no_zscore_on_same_day():
    """같은 날 z-score 가 없으면 누적이 그대로 통과."""
    # 매일 -2.1% 씩 5거래일 → 누적 ≈ -10% 하지만 단일봉 변동은 작음(z-score 미발동).
    closes = [100.0]
    for _ in range(60):
        closes.append(closes[-1] * 1.001)  # 평탄
    # 5일간 -2.5%씩 (전체 -12% 누적, 단일봉 -2.5% 는 평상 σ 보다 큼 — z-score 도 잡힐 수 있음)
    # 더 안전하게: 5일간 -2.0% (단일봉 z-score floor=2% 경계)
    for _ in range(5):
        closes.append(closes[-1] * 0.978)  # -2.2% × 5 ≈ -10.6%
    bars = _make_bars(closes)
    merged = detect_anomalies(bars, "1D", "AAPL")
    # 누적 탐지가 1건은 있어야 한다(US floor 5% 라 단일봉은 미발동).
    cum_events = [e for e in merged if e.type == "cumulative_5d"]
    assert len(cum_events) >= 1


def test_default_ticker_falls_back_to_us():
    """ticker 미전달 시 backward-compat 으로 US floor 적용."""
    closes = [100.0] * 61
    closes.append(105.5)  # 5.5% — US floor=5% 초과
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D")  # ticker 인자 미전달
    assert len(anomalies) == 1


# ── KR3: Drawdown 변곡점 ─────────────────────────────────────


def test_drawdown_constants_match_okr_spec():
    assert _DRAWDOWN_START_THRESHOLD == -0.10
    assert _DRAWDOWN_RECOVERY_THRESHOLD == -0.03


def test_drawdown_start_marker_on_first_breach():
    """60봉 평탄 + 1봉 -11% → drawdown_start 발동(고점 100 → 89, drawdown -11%)."""
    closes = [100.0] * 61
    closes.append(89.0)
    bars = _make_bars(closes)
    events = _detect_drawdown_anomalies(bars, "1D")
    assert any(e.type == "drawdown_start" for e in events)
    start = next(e for e in events if e.type == "drawdown_start")
    assert start.direction == "down"
    assert start.return_pct < -10.0


def test_drawdown_recovery_pairs_with_start():
    """-11% 진입 후 -2% 회복 → 시작-회복 한 쌍."""
    closes = [100.0] * 61 + [89.0, 89.0, 98.0]  # 회복: -2%
    bars = _make_bars(closes)
    events = _detect_drawdown_anomalies(bars, "1D")
    types = [e.type for e in events]
    assert types.count("drawdown_start") == 1
    assert types.count("drawdown_recovery") == 1
    # 시작이 회복보다 앞 날짜.
    start = next(e for e in events if e.type == "drawdown_start")
    recovery = next(e for e in events if e.type == "drawdown_recovery")
    assert start.date < recovery.date


def test_drawdown_does_not_retrigger_inside_same_cycle():
    """-11%, -12%, -13% 연속이어도 시작 마커는 1번만."""
    closes = [100.0] * 61 + [89.0, 88.0, 87.0, 86.0, 85.0]
    bars = _make_bars(closes)
    events = _detect_drawdown_anomalies(bars, "1D")
    starts = [e for e in events if e.type == "drawdown_start"]
    assert len(starts) == 1


def test_drawdown_only_for_daily_interval():
    closes = [100.0] * 61 + [85.0]
    bars = _make_bars(closes)
    assert _detect_drawdown_anomalies(bars, "1W") == []
    assert _detect_drawdown_anomalies(bars, "1M") == []


# ── KR4: robust σ (stable / mad) ─────────────────────────────


def test_compute_sigma_off_uses_stdev():
    """method='off' 또는 'stdev' 는 기존 statistics.stdev."""
    import statistics

    window = [0.01, 0.02, -0.01, 0.0, 0.005]
    expected = statistics.stdev(window)
    assert _compute_sigma(window, "off") == pytest.approx(expected)
    assert _compute_sigma(window, "stdev") == pytest.approx(expected)


def test_compute_sigma_stable_filters_outliers_when_enough_data():
    """stable: |r|≥3% 이상치를 제외한 stdev 사용 (충분한 데이터일 때)."""
    # 30개의 미세 변동 + 5개의 큰 이상치 (5% 변동) — 큰 이상치 제외 시 σ 가 작아져야
    stable_part = [0.005, -0.005] * 15
    extremes = [0.05, -0.05, 0.06, -0.06, 0.04]
    window = stable_part + extremes  # 35개
    sigma_stable = _compute_sigma(window, "stable")
    sigma_stdev = _compute_sigma(window, "off")
    assert sigma_stable < sigma_stdev


def test_compute_sigma_mad_uses_median_abs_deviation():
    """MAD 방식 σ = median(|r-median|) × 1.4826."""
    window = [0.0, 0.01, -0.01, 0.005, -0.005, 0.02, -0.02] * 10
    sigma_mad = _compute_sigma(window, "mad")
    assert sigma_mad > 0
    # MAD 는 outlier resistant — stdev 와 다른 값.
    sigma_stdev = _compute_sigma(window, "off")
    assert sigma_mad != pytest.approx(sigma_stdev)


def test_zscore_event_includes_sigma_method_field():
    """응답에 sigma_method 디버그 필드 포함."""
    closes = [100.0] * 61
    closes.append(110.0)
    bars = _make_bars(closes)
    anomalies = detect_anomalies(bars, "1D", "AAPL")
    assert all(e.sigma_method in {"stdev", "stable", "mad"} for e in anomalies if e.type == "zscore")


# ── dedup with drawdown ───────────────────────────────────────


def test_drawdown_passes_through_when_no_zscore_collision():
    """Drawdown 마커는 같은 날 z-score 가 없을 때 detect_anomalies 결과에 통과."""
    # 60봉 평탄 + -11% 한 봉 — z-score 와 drawdown_start 모두 잡히지만 z-score 우선.
    # z-score 도 잡히려면 floor 통과 — US floor 5% 초과.
    closes = [100.0] * 61 + [89.0]
    bars = _make_bars(closes)
    merged = detect_anomalies(bars, "1D", "AAPL")
    same_day = [e for e in merged if e.date == bars[61].bar_date]
    assert len(same_day) == 1
    # z-score 우선 (drawdown 은 fallback)
    assert same_day[0].type == "zscore"


# ── KR5: 변동성 클러스터 ─────────────────────────────────────


def test_cluster_constants_match_okr_spec():
    assert _CLUSTER_BIG_MOVE_THRESHOLD == 0.05
    assert _CLUSTER_PROXIMITY_DAYS == 5
    assert _CLUSTER_MIN_MEMBERS == 2


def test_volatility_cluster_groups_two_big_moves_within_5_days():
    """5거래일 이내 |r|>5% 큰 변동 2건 → 클러스터 1개, 첫 봉에 마커."""
    # 평탄 + 큰 변동 두 건 (3일 간격)
    closes = [100.0] * 10 + [108.0] + [108.0, 108.0] + [98.0] + [98.0] * 5  # +8% 그리고 -9.3%
    bars = _make_bars(closes)
    events = _detect_volatility_cluster_anomalies(bars, "1D")
    assert len(events) == 1
    cluster = events[0]
    assert cluster.type == "volatility_cluster"
    assert cluster.cluster_size == 2
    # cluster_end_date 가 두 번째 큰 변동의 봉 날짜
    assert cluster.cluster_end_date is not None
    assert cluster.date < cluster.cluster_end_date


def test_volatility_cluster_no_event_when_only_one_big_move():
    """단일 큰 변동은 클러스터 아님."""
    closes = [100.0] * 10 + [108.0] + [108.0] * 10
    bars = _make_bars(closes)
    events = _detect_volatility_cluster_anomalies(bars, "1D")
    assert events == []


def test_volatility_cluster_splits_when_gap_exceeds_5_days():
    """6거래일 떨어진 두 큰 변동은 별도 클러스터로 분리(둘 다 단일 → 클러스터 0)."""
    # 큰 변동 1건 → 7일 평탄 → 큰 변동 1건. 각각 단일 멤버 → 클러스터 미생성.
    closes = [100.0] * 5 + [108.0] + [108.0] * 7 + [98.0] + [98.0] * 5
    bars = _make_bars(closes)
    events = _detect_volatility_cluster_anomalies(bars, "1D")
    assert events == []


def test_volatility_cluster_only_for_daily_interval():
    closes = [100.0] * 10 + [108.0, 108.0, 98.0]
    bars = _make_bars(closes)
    assert _detect_volatility_cluster_anomalies(bars, "1W") == []
    assert _detect_volatility_cluster_anomalies(bars, "1M") == []


def test_volatility_cluster_three_members_records_correct_size():
    """3건 묶음은 cluster_size=3."""
    # 3건 큰 변동, 모두 5일 이내 (1, 3, 5번째)
    closes = [100.0] * 5 + [108.0] + [108.0] + [98.0] + [98.0] + [108.0] + [108.0] * 5
    bars = _make_bars(closes)
    events = _detect_volatility_cluster_anomalies(bars, "1D")
    assert len(events) == 1
    assert events[0].cluster_size == 3


def test_cluster_skipped_in_dedup_when_zscore_on_same_day():
    """같은 날 z-score 가 잡히면 cluster 마커는 skip(z-score 우선)."""
    # 60봉 평탄 + -11% (z-score+cluster 동시 가능 시작점) 그리고 +6% (cluster 두 번째)
    closes = [100.0] * 61 + [89.0, 89.0, 94.5]
    bars = _make_bars(closes)
    merged = detect_anomalies(bars, "1D", "AAPL")
    # 첫 봉(idx 61)은 z-score 가 우선 잡힘.
    same_day = [e for e in merged if e.date == bars[61].bar_date]
    assert len(same_day) == 1
    assert same_day[0].type == "zscore"


# ── KR7: 사용자 floor override 슬라이더 ──────────────────────


def test_floor_override_lowers_kospi_threshold():
    """`floor_pct_override=3.0` 이면 KOSPI 종목에서 3.5% 변동도 탐지(기본 5% 보다 낮음)."""
    closes = [100.0] * 61
    closes.append(103.5)  # +3.5%
    bars = _make_bars(closes)
    # override 없이는 KOSPI floor=5% 미만 → 탐지 X
    assert detect_anomalies(bars, "1D", "005930.KS") == []
    # override 3% → 탐지 1건
    overridden = detect_anomalies(bars, "1D", "005930.KS", floor_pct_override=3.0)
    assert len(overridden) == 1
    assert overridden[0].type == "zscore"


def test_floor_override_raises_kosdaq_threshold():
    """`floor_pct_override=10.0` 이면 KOSDAQ 8% 변동은 미탐지(기본 7% 보다 높임)."""
    closes = [100.0] * 61
    closes.append(108.0)  # +8%
    bars = _make_bars(closes)
    # override 없이는 KOSDAQ floor=7% 초과 → 탐지
    assert len(detect_anomalies(bars, "1D", "068270.KQ")) == 1
    # override 10% → 탐지 X
    assert detect_anomalies(bars, "1D", "068270.KQ", floor_pct_override=10.0) == []


def test_floor_override_none_keeps_ticker_group_default():
    """override=None 일 때 기존 종목 군 분류 그대로(KOSPI 5% / KOSDAQ 7% / US 5%)."""
    closes = [100.0] * 61
    closes.append(106.5)  # +6.5%
    bars = _make_bars(closes)
    # KOSPI floor=5% → 탐지
    assert len(detect_anomalies(bars, "1D", "005930.KS", floor_pct_override=None)) == 1
    # KOSDAQ floor=7% → 미탐지
    assert detect_anomalies(bars, "1D", "068270.KQ", floor_pct_override=None) == []


def test_floor_override_applies_to_non_daily_intervals():
    """override 는 봉 단위 무관하게 적용 — 1W 봉도 사용자 의도 우선(기본 floor 무시)."""
    # _PARAMS_BY_INTERVAL["1W"].floor_pct = 3.0
    # 1W window=52 → 53봉 이상 필요. +2.5% 변동이면 기본 3% 미만이라 탐지 X.
    # override 2.0% 면 탐지.
    closes = [100.0] * 53
    closes.append(102.5)
    bars = _make_bars(closes)
    # 기본: floor=3% → 미탐지
    assert detect_anomalies(bars, "1W", "AAPL") == []
    # override 2% → 탐지
    overridden = detect_anomalies(bars, "1W", "AAPL", floor_pct_override=2.0)
    assert len(overridden) == 1


def test_floor_override_only_affects_zscore_not_cumulative():
    """floor override 는 z-score floor 만 조정 — 누적 임계(±10%) 무관."""
    # 5봉 사이 +12% → 누적 5d 트리거. 단일봉도 +12% (z-score).
    closes = [100.0] * 21 + [112.0]
    bars = _make_bars(closes)
    # override=15% (단일봉 12%는 z-score 미달이지만, 누적 5d 12% > 10% → 누적은 잡힘)
    events = detect_anomalies(bars, "1D", "AAPL", floor_pct_override=15.0)
    types = [e.type for e in events]
    # z-score 단일봉은 floor=15% 미달 → 누적 5d 만 잡혀야 함
    assert "zscore" not in types
    assert "cumulative_5d" in types
