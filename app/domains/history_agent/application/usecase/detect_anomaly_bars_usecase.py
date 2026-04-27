"""차트 이상치 봉 감지 UseCase (§13.4 C, §17.2, OKR 다층 탐지).

다층 탐지기:
1. **z-score (기존)** — 봉 단위 adaptive threshold (k·σ + floor) 로 "이 봉이 평상시보다 특이한가"
2. **cumulative window (KR2)** — 1D 에서 5/20일 누적 수익률 ±10/15% 임계 진입 봉
3. **drawdown (KR3)** — 1D 에서 60봉 고점 대비 -10% 시작 / -3% 회복 변곡점
4. **robust σ (KR4 디버그)** — settings.anomaly_robust_sigma_method 로 stable/mad 방식 swap
5. **volatility cluster (KR5)** — 1D 에서 5거래일 이내 |r|>5% 큰 변동 2건 이상 묶음의 첫 봉

- k: 2.5 공통 (표준편차 배수)
- window: 봉 단위별 σ 추정 기간
- floor: 봉 단위별 절대 하한 변동률(%) — 1D 에선 KR1 종목 군별 floor 가 우선
- max_count: 봉 단위별 최대 마커 수

KR1 종목 군별 floor 우선순위 (1D 에만 적용):
- KOSPI(`.KS`): 5%   / KOSDAQ(`.KQ`): 7%   / 그 외(미국 등): 5%
"""
import logging
import math
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.history_agent.application.response.anomaly_bar_response import (
    AnomalyBarResponse,
    AnomalyBarsResponse,
)
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _IntervalParams:
    k: float
    window: int
    floor_pct: float
    max_count: int


# §17.2 표. k 공통 2.5. floor는 봉 단위 증가에 따라 상향 (시간 범위가 길수록 noise floor↑).
_PARAMS_BY_INTERVAL: dict[str, _IntervalParams] = {
    "1D": _IntervalParams(k=2.5, window=60,  floor_pct=2.0,  max_count=20),
    "1W": _IntervalParams(k=2.5, window=52,  floor_pct=3.0,  max_count=15),
    "1M": _IntervalParams(k=2.5, window=36,  floor_pct=5.0,  max_count=10),
    "1Q": _IntervalParams(k=2.5, window=40,  floor_pct=10.0, max_count=5),
}


# KR1 — 종목 군별 1D floor (`max(k×σ, group_floor)`).
# 군 식별은 yfinance ticker suffix 기반(.KS=KOSPI, .KQ=KOSDAQ, 그 외=US).
_FLOOR_BY_TICKER_GROUP_1D: Dict[str, float] = {
    "KOSPI": 5.0,
    "KOSDAQ": 7.0,
    "US": 5.0,
}


def _classify_ticker_group(ticker: str) -> str:
    """yfinance suffix 로 거래소 군 분류. 미정의 종목은 'US' 로 fallback(보수적)."""
    upper = (ticker or "").upper()
    if upper.endswith(".KS"):
        return "KOSPI"
    if upper.endswith(".KQ"):
        return "KOSDAQ"
    return "US"


def _floor_pct_for(
    chart_interval: str,
    ticker: str,
    default: float,
    override: Optional[float] = None,
) -> float:
    """floor 결정 우선순위:

    1. `override` 가 주어지면 사용자 명시 의도 → 종목 군/봉 단위 분류 모두 무시
    2. 1D 면 종목 군별 floor (`_FLOOR_BY_TICKER_GROUP_1D`)
    3. 그 외 봉 단위는 default(`_PARAMS_BY_INTERVAL`) 그대로
    """
    if override is not None:
        return override
    if chart_interval != "1D":
        return default
    return _FLOOR_BY_TICKER_GROUP_1D.get(_classify_ticker_group(ticker), default)


# KR2 — 누적 윈도우 임계값(1D 전용).
# 임계 이상으로 처음 진입한 봉만 마커 trigger — 빠져나간 후 재진입 시 재 트리거.
_CUMULATIVE_5D_THRESHOLD = 0.10   # ±10%
_CUMULATIVE_20D_THRESHOLD = 0.15  # ±15%

# KR3 — Drawdown 변곡점 (1D 전용).
# 60봉 고점 대비 -10% 첫 진입 → start, -3% 회복 → recovery. 같은 사이클에서 한 쌍.
_DRAWDOWN_WINDOW = 60
_DRAWDOWN_START_THRESHOLD = -0.10
_DRAWDOWN_RECOVERY_THRESHOLD = -0.03

# KR4 — robust σ 디버그 모드. stable filter A안의 안정 구간 임계값.
_STABLE_RETURN_THRESHOLD = 0.03  # |r|<3% 만 σ 추정 입력
_MAD_TO_SIGMA_FACTOR = 1.4826    # 정규분포 환산

# KR5 — 변동성 클러스터 (1D 전용).
_CLUSTER_BIG_MOVE_THRESHOLD = 0.05   # |r|>5% 큰 변동
_CLUSTER_PROXIMITY_DAYS = 5          # 5거래일 이내
_CLUSTER_MIN_MEMBERS = 2             # 최소 2건 이상 묶음만 클러스터


def _compute_returns(bars: List[StockBar]) -> list[float]:
    """봉 단위 일(또는 주/월/분기)수익률. bars 배열과 **1만큼 짧은** 배열 반환.

    idx i 의 return = (bars[i+1].close - bars[i].close) / bars[i].close
    """
    returns: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        if prev_close <= 0:
            returns.append(0.0)
            continue
        returns.append(bars[i].close / prev_close - 1.0)
    return returns


def _volume_ratio(bars: List[StockBar], idx: int, window: int) -> Optional[float]:
    """idx 봉의 거래량을 직전 window 봉 평균 대비 배수로 환산. 평균이 0/window 부족이면 None."""
    if idx < window:
        return None
    window_volumes = [bars[j].volume for j in range(idx - window, idx) if bars[j].volume > 0]
    if not window_volumes:
        return None
    avg = sum(window_volumes) / len(window_volumes)
    if avg <= 0:
        return None
    return round(bars[idx].volume / avg, 4)


def _time_of_day(bars: List[StockBar], idx: int, chart_interval: str) -> Optional[str]:
    """일봉(1D)에서만 갭/장중 근사. |open-prev_close| > |close-open| → "GAP".

    분봉 미수집 환경의 best-effort 근사. 주/월/분기봉은 의미가 없어 None.
    """
    if chart_interval != "1D" or idx <= 0:
        return None
    bar = bars[idx]
    prev_close = bars[idx - 1].close
    if prev_close <= 0:
        return None
    gap = abs(bar.open - prev_close)
    intraday = abs(bar.close - bar.open)
    if gap == 0 and intraday == 0:
        return None
    return "GAP" if gap > intraday else "INTRADAY"


def _cumulative_return(bars: List[StockBar], idx: int, n: int) -> Optional[float]:
    """spike 봉(idx) 종가 기준 +n봉 후 raw 누적 수익률(%). 미래 데이터 부족하면 None.

    봉 단위 무관 — 일봉이면 +n거래일, 주봉이면 +n주. benchmark 미차감(raw).
    """
    target_idx = idx + n
    if target_idx >= len(bars):
        return None
    base = bars[idx].close
    if base <= 0:
        return None
    return round((bars[target_idx].close / base - 1.0) * 100.0, 4)


def _compute_sigma(window_slice: list[float], method: str) -> float:
    """KR4 — σ 추정 방식. method 별로 다른 알고리즘 사용.

    "off"/"stdev"  — 기존 statistics.stdev (default)
    "stable"       — 안정 구간(|r|<3%) 만 stdev 계산 (이상치 제외)
    "mad"          — Median Absolute Deviation × 1.4826 (정규분포 환산)
    """
    if not window_slice:
        return 0.0
    if method == "stable":
        stable = [r for r in window_slice if abs(r) < _STABLE_RETURN_THRESHOLD]
        # 데이터 부족하면 fallback to stdev (변동성 자체가 큰 종목)
        target = stable if len(stable) >= 30 else window_slice
        try:
            return statistics.stdev(target)
        except statistics.StatisticsError:
            return 0.0
    if method == "mad":
        try:
            median = statistics.median(window_slice)
            deviations = [abs(r - median) for r in window_slice]
            mad = statistics.median(deviations)
            return mad * _MAD_TO_SIGMA_FACTOR
        except statistics.StatisticsError:
            return 0.0
    # "off" / "stdev" / 미정의 — 기존 stdev
    try:
        return statistics.stdev(window_slice)
    except statistics.StatisticsError:
        return 0.0


def _resolve_sigma_method() -> str:
    """settings 에서 robust σ method 읽기. 미정의 값은 'stdev' fallback."""
    raw = (get_settings().anomaly_robust_sigma_method or "off").lower()
    if raw in {"stable", "mad"}:
        return raw
    return "stdev"


def _detect_zscore_anomalies(
    bars: List[StockBar],
    chart_interval: str,
    ticker: str,
    floor_pct_override: Optional[float] = None,
) -> List[AnomalyBarResponse]:
    """단일봉 z-score 탐지 (기존 로직 + KR1 종목 군별 floor + KR4 robust σ)."""
    params = _PARAMS_BY_INTERVAL.get(chart_interval)
    if params is None:
        raise ValueError(f"Unsupported chart_interval: {chart_interval!r}")

    if len(bars) <= params.window + 1:
        return []

    returns = _compute_returns(bars)
    candidates: list[tuple[int, float, float]] = []  # (idx, return_pct, z_score)
    floor_abs = _floor_pct_for(chart_interval, ticker, params.floor_pct, override=floor_pct_override) / 100.0
    sigma_method = _resolve_sigma_method()

    for i in range(params.window, len(returns)):
        window_slice = returns[i - params.window: i]
        sigma = _compute_sigma(window_slice, sigma_method)
        if math.isnan(sigma) or sigma < 0:
            sigma = 0.0

        # KR1 — z-score OR floor 결합. σ 가 0/극소여도 floor 만 통과하면 잡는다.
        threshold = max(params.k * sigma, floor_abs) if sigma > 0 else floor_abs
        r = returns[i]
        if abs(r) < threshold:
            continue

        z = r / sigma if sigma > 0 else 0.0
        candidates.append((i + 1, r * 100.0, z))

    # |z| 우선 → 동률(σ=0 케이스) 은 |return_pct| 큰 순으로 백업 정렬.
    candidates.sort(key=lambda x: (abs(x[2]), abs(x[1])), reverse=True)
    top = candidates[: params.max_count]

    return [
        AnomalyBarResponse(
            date=bars[idx].bar_date,
            type="zscore",
            return_pct=round(ret_pct, 4),
            z_score=round(z, 4),
            direction="up" if ret_pct > 0 else "down",
            close=round(bars[idx].close, 4),
            volume_ratio=_volume_ratio(bars, idx, params.window),
            time_of_day=_time_of_day(bars, idx, chart_interval),
            cumulative_return_1d=_cumulative_return(bars, idx, 1),
            cumulative_return_5d=_cumulative_return(bars, idx, 5),
            cumulative_return_20d=_cumulative_return(bars, idx, 20),
            sigma_method=sigma_method,
            causality=None,
        )
        for idx, ret_pct, z in top
    ]


def _detect_cumulative_anomalies(
    bars: List[StockBar], chart_interval: str,
) -> List[AnomalyBarResponse]:
    """KR2 — 5/20일 누적 윈도우 탐지기.

    임계값(±10% / ±15%) 이상으로 **처음 진입한 봉**만 마커. 다음 봉이 임계 안으로
    빠져나가면 trigger 가 재무장됨(재진입 시 재 마커). 임계 안에서 진동하는 작은
    fluctuation 은 무시되어 `잔잔한 연속 하락` 누적이 임계 넘어서는 시점만 잡힌다.

    1D 만 동작. 1W/1M/1Q 는 봉 자체가 길어 누적 의미가 약함 — 빈 리스트 반환.
    z-score 와의 dedup 은 호출자(`detect_anomalies`) 가 담당.
    """
    if chart_interval != "1D":
        return []
    if len(bars) <= 21:
        return []

    events: List[AnomalyBarResponse] = []
    # trigger 재무장 플래그. 직전 봉이 임계 밖이었으면 True.
    armed_5d = True
    armed_20d = True

    for i in range(5, len(bars)):
        prev = bars[i - 5].close
        if prev <= 0:
            armed_5d = True
            continue
        ret_5d = bars[i].close / prev - 1.0
        is_above_5d = abs(ret_5d) > _CUMULATIVE_5D_THRESHOLD
        if is_above_5d and armed_5d:
            events.append(
                AnomalyBarResponse(
                    date=bars[i].bar_date,
                    type="cumulative_5d",
                    return_pct=round(ret_5d * 100.0, 4),
                    z_score=0.0,
                    direction="up" if ret_5d > 0 else "down",
                    close=round(bars[i].close, 4),
                    volume_ratio=_volume_ratio(bars, i, 60),
                    time_of_day=_time_of_day(bars, i, chart_interval),
                    cumulative_return_1d=_cumulative_return(bars, i, 1),
                    cumulative_return_5d=_cumulative_return(bars, i, 5),
                    cumulative_return_20d=_cumulative_return(bars, i, 20),
                    causality=None,
                )
            )
        armed_5d = not is_above_5d

    for i in range(20, len(bars)):
        prev = bars[i - 20].close
        if prev <= 0:
            armed_20d = True
            continue
        ret_20d = bars[i].close / prev - 1.0
        is_above_20d = abs(ret_20d) > _CUMULATIVE_20D_THRESHOLD
        if is_above_20d and armed_20d:
            events.append(
                AnomalyBarResponse(
                    date=bars[i].bar_date,
                    type="cumulative_20d",
                    return_pct=round(ret_20d * 100.0, 4),
                    z_score=0.0,
                    direction="up" if ret_20d > 0 else "down",
                    close=round(bars[i].close, 4),
                    volume_ratio=_volume_ratio(bars, i, 60),
                    time_of_day=_time_of_day(bars, i, chart_interval),
                    cumulative_return_1d=_cumulative_return(bars, i, 1),
                    cumulative_return_5d=_cumulative_return(bars, i, 5),
                    cumulative_return_20d=_cumulative_return(bars, i, 20),
                    causality=None,
                )
            )
        armed_20d = not is_above_20d

    return events


def _detect_drawdown_anomalies(
    bars: List[StockBar], chart_interval: str,
) -> List[AnomalyBarResponse]:
    """KR3 — 60봉 고점 대비 Drawdown 변곡점 (1D 전용).

    - drawdown_start: -10% 이하로 첫 진입한 봉. 같은 사이클에선 1번만 trigger.
    - drawdown_recovery: drawdown 진행 중 -3% 이내로 회복한 봉. 사이클 종료.
    한 사이클에서 시작-회복 마커 한 쌍이 일관되게 표시된다.
    """
    if chart_interval != "1D":
        return []
    if len(bars) <= _DRAWDOWN_WINDOW:
        return []

    events: List[AnomalyBarResponse] = []
    in_drawdown = False  # 현재 -10% 이하 사이클 진행 중인지

    for i in range(_DRAWDOWN_WINDOW, len(bars)):
        # 60봉 high water mark (현재 봉 포함)
        window_closes = [bars[j].close for j in range(i - _DRAWDOWN_WINDOW, i + 1)]
        high = max(window_closes) if window_closes else 0.0
        if high <= 0:
            continue
        drawdown = (bars[i].close - high) / high  # 음수(또는 0)

        if not in_drawdown and drawdown <= _DRAWDOWN_START_THRESHOLD:
            events.append(
                AnomalyBarResponse(
                    date=bars[i].bar_date,
                    type="drawdown_start",
                    return_pct=round(drawdown * 100.0, 4),
                    z_score=0.0,
                    direction="down",
                    close=round(bars[i].close, 4),
                    volume_ratio=_volume_ratio(bars, i, _DRAWDOWN_WINDOW),
                    time_of_day=_time_of_day(bars, i, chart_interval),
                    cumulative_return_1d=_cumulative_return(bars, i, 1),
                    cumulative_return_5d=_cumulative_return(bars, i, 5),
                    cumulative_return_20d=_cumulative_return(bars, i, 20),
                    causality=None,
                )
            )
            in_drawdown = True
        elif in_drawdown and drawdown >= _DRAWDOWN_RECOVERY_THRESHOLD:
            events.append(
                AnomalyBarResponse(
                    date=bars[i].bar_date,
                    type="drawdown_recovery",
                    return_pct=round(drawdown * 100.0, 4),
                    z_score=0.0,
                    direction="up",
                    close=round(bars[i].close, 4),
                    volume_ratio=_volume_ratio(bars, i, _DRAWDOWN_WINDOW),
                    time_of_day=_time_of_day(bars, i, chart_interval),
                    cumulative_return_1d=_cumulative_return(bars, i, 1),
                    cumulative_return_5d=_cumulative_return(bars, i, 5),
                    cumulative_return_20d=_cumulative_return(bars, i, 20),
                    causality=None,
                )
            )
            in_drawdown = False

    return events


def _detect_volatility_cluster_anomalies(
    bars: List[StockBar], chart_interval: str,
) -> List[AnomalyBarResponse]:
    """KR5 — 변동성 클러스터 (1D 전용).

    |r|>5% 큰 변동 봉들을 5거래일 이내 그룹으로 묶고, 2건 이상이면 클러스터.
    클러스터의 **첫 봉**에만 type="volatility_cluster" 마커를 1개 부여하고,
    cluster_size 와 cluster_end_date 메타로 구간 정보 보존. frontend 가
    이 정보로 시작-끝 차트 음영 영역과 헤더 라벨을 그릴 수 있다.

    OKR 명세상 클러스터 내 개별 봉 마커 숨김은 frontend(KR7) 가 토글로 처리한다.
    """
    if chart_interval != "1D":
        return []
    if len(bars) <= 5:
        return []

    returns = _compute_returns(bars)
    big_idx: list[int] = []
    for i, r in enumerate(returns):
        if abs(r) > _CLUSTER_BIG_MOVE_THRESHOLD:
            big_idx.append(i + 1)  # bars 인덱스(returns[i] = bars[i+1] 의 변동)

    if len(big_idx) < _CLUSTER_MIN_MEMBERS:
        return []

    # 5거래일 이내 그룹핑.
    clusters: list[list[int]] = []
    current: list[int] = []
    for idx in big_idx:
        if not current or idx - current[-1] <= _CLUSTER_PROXIMITY_DAYS:
            current.append(idx)
        else:
            if len(current) >= _CLUSTER_MIN_MEMBERS:
                clusters.append(current)
            current = [idx]
    if len(current) >= _CLUSTER_MIN_MEMBERS:
        clusters.append(current)

    events: List[AnomalyBarResponse] = []
    for cluster in clusters:
        first_idx = cluster[0]
        last_idx = cluster[-1]
        # 클러스터 첫 봉의 변동률.
        first_return_pct = returns[first_idx - 1] * 100.0 if first_idx >= 1 else 0.0
        events.append(
            AnomalyBarResponse(
                date=bars[first_idx].bar_date,
                type="volatility_cluster",
                return_pct=round(first_return_pct, 4),
                z_score=0.0,
                direction="up" if first_return_pct > 0 else "down",
                close=round(bars[first_idx].close, 4),
                volume_ratio=_volume_ratio(bars, first_idx, 60),
                time_of_day=_time_of_day(bars, first_idx, chart_interval),
                cumulative_return_1d=_cumulative_return(bars, first_idx, 1),
                cumulative_return_5d=_cumulative_return(bars, first_idx, 5),
                cumulative_return_20d=_cumulative_return(bars, first_idx, 20),
                cluster_size=len(cluster),
                cluster_end_date=bars[last_idx].bar_date,
                causality=None,
            )
        )

    return events


def detect_anomalies(
    bars: List[StockBar],
    chart_interval: str,
    ticker: str = "",
    floor_pct_override: Optional[float] = None,
) -> List[AnomalyBarResponse]:
    """순수 함수 — bars + interval + ticker → 이상치 봉 목록.

    z-score + 누적 + drawdown + cluster 결과를 dedup 정책에 따라 합쳐 반환:
    - 같은 날 z-score 와 다른 type 충돌 → **z-score 우선**
    - 같은 날 5일 누적 + 20일 누적 → **20일 우선**
    - drawdown / volatility_cluster 는 같은 날 다른 마커 있으면 skip
    날짜 오름차순 정렬.

    `ticker` default `""` 는 backward-compat — 종목 군 분류 없이 미국(US) fallback.
    `floor_pct_override` 는 KR7 슬라이더용 — z-score floor 만 override (누적/drawdown 무관).
    """
    zscore_events = _detect_zscore_anomalies(
        bars, chart_interval, ticker, floor_pct_override=floor_pct_override,
    )
    cumulative_events = _detect_cumulative_anomalies(bars, chart_interval)
    drawdown_events = _detect_drawdown_anomalies(bars, chart_interval)
    cluster_events = _detect_volatility_cluster_anomalies(bars, chart_interval)

    by_date: Dict[object, AnomalyBarResponse] = {}
    # z-score 우선 → 먼저 채움.
    for ev in zscore_events:
        by_date[ev.date] = ev
    # 누적: 같은 날 z-score 가 있으면 skip, 없으면 저장. 5일 < 20일 우선.
    for ev in cumulative_events:
        if ev.date in by_date:
            existing = by_date[ev.date]
            if existing.type == "zscore":
                continue
            if existing.type == "cumulative_5d" and ev.type == "cumulative_20d":
                by_date[ev.date] = ev
            continue
        by_date[ev.date] = ev
    # Drawdown: 같은 날 다른 마커 있으면 skip(누적/z-score 우선).
    for ev in drawdown_events:
        if ev.date not in by_date:
            by_date[ev.date] = ev
    # Volatility cluster: 같은 날 다른 마커 있으면 skip(z-score 등 우선).
    # 클러스터 마커는 frontend KR7 토글로 ON/OFF 가능하므로, dedup 보다는 추가 정보로 활용.
    for ev in cluster_events:
        if ev.date not in by_date:
            by_date[ev.date] = ev

    merged = sorted(by_date.values(), key=lambda e: e.date)
    return merged


class DetectAnomalyBarsUseCase:
    """엔드포인트에서 호출하는 UseCase 래퍼."""

    def __init__(self, stock_bars_port: StockBarsPort):
        self._stock_bars_port = stock_bars_port

    async def execute(
        self,
        ticker: str,
        chart_interval: str,
        floor_pct_override: Optional[float] = None,
    ) -> AnomalyBarsResponse:
        _, bars = await self._stock_bars_port.fetch_stock_bars(
            ticker=ticker, chart_interval=chart_interval
        )
        events = detect_anomalies(
            bars, chart_interval, ticker, floor_pct_override=floor_pct_override,
        )
        counts = {
            "zscore": sum(1 for e in events if e.type == "zscore"),
            "cumulative_5d": sum(1 for e in events if e.type == "cumulative_5d"),
            "cumulative_20d": sum(1 for e in events if e.type == "cumulative_20d"),
            "drawdown_start": sum(1 for e in events if e.type == "drawdown_start"),
            "drawdown_recovery": sum(1 for e in events if e.type == "drawdown_recovery"),
            "volatility_cluster": sum(1 for e in events if e.type == "volatility_cluster"),
        }
        logger.info(
            "[DetectAnomalyBars] ticker=%s chart_interval=%s bars=%d anomalies=%d floor_override=%s %s",
            ticker, chart_interval, len(bars), len(events), floor_pct_override, counts,
        )
        return AnomalyBarsResponse(
            ticker=ticker,
            chart_interval=chart_interval,
            count=len(events),
            events=events,
        )
