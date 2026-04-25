"""차트 이상치 봉 감지 UseCase (§13.4 C, §17.2).

봉 단위별 adaptive threshold (k·σ + floor)로 "이 봉이 평상시보다 특이한가"를 판정.
PRICE 카테고리(과거 `_from_price_events`)를 완전히 대체.

- k: 2.5 공통 (표준편차 배수)
- window: 봉 단위별 σ 추정 기간 (일봉 60거래일, 주봉 52주, 월봉 36개월, 분기봉 40분기)
- floor: 봉 단위별 절대 하한 변동률(%)
- max_count: 봉 단위별 최대 마커 수 (차트 과밀 방지)

향후 follow-up (🅒): 종목별 β 고려해 k 동적 조정.
"""
import logging
import math
import statistics
from dataclasses import dataclass
from typing import List

from app.domains.dashboard.application.port.out.stock_bars_port import StockBarsPort
from app.domains.dashboard.domain.entity.stock_bar import StockBar
from app.domains.history_agent.application.response.anomaly_bar_response import (
    AnomalyBarResponse,
    AnomalyBarsResponse,
)

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


def detect_anomalies(
    bars: List[StockBar], chart_interval: str
) -> List[AnomalyBarResponse]:
    """순수 함수 — bars + interval → 이상치 봉 목록. 테스트 편의용 분리."""
    params = _PARAMS_BY_INTERVAL.get(chart_interval)
    if params is None:
        raise ValueError(f"Unsupported chart_interval: {chart_interval!r}")

    if len(bars) <= params.window + 1:
        # σ 추정에 충분한 데이터가 없음 — 빈 결과 반환.
        return []

    returns = _compute_returns(bars)
    candidates: list[tuple[int, float, float]] = []  # (idx, return_pct, z_score)
    floor_abs = params.floor_pct / 100.0

    for i in range(params.window, len(returns)):
        window_slice = returns[i - params.window: i]
        try:
            sigma = statistics.stdev(window_slice)
        except statistics.StatisticsError:
            continue
        if sigma <= 0 or math.isnan(sigma):
            continue

        threshold = max(params.k * sigma, floor_abs)
        r = returns[i]
        if abs(r) < threshold:
            continue

        z = r / sigma if sigma else 0.0
        # returns[i] → bars[i+1]의 수익률
        candidates.append((i + 1, r * 100.0, z))

    # |z_score| 기준 상위 max_count 개만 선별 — 차트 과밀 방지.
    candidates.sort(key=lambda x: abs(x[2]), reverse=True)
    top = candidates[: params.max_count]

    # 다시 날짜 오름차순으로 정렬해 프론트 렌더 편의 확보.
    top.sort(key=lambda x: bars[x[0]].bar_date)

    return [
        AnomalyBarResponse(
            date=bars[idx].bar_date,
            return_pct=round(ret_pct, 4),
            z_score=round(z, 4),
            direction="up" if ret_pct > 0 else "down",
            close=round(bars[idx].close, 4),
            causality=None,
        )
        for idx, ret_pct, z in top
    ]


class DetectAnomalyBarsUseCase:
    """엔드포인트에서 호출하는 UseCase 래퍼."""

    def __init__(self, stock_bars_port: StockBarsPort):
        self._stock_bars_port = stock_bars_port

    async def execute(
        self, ticker: str, chart_interval: str
    ) -> AnomalyBarsResponse:
        _, bars = await self._stock_bars_port.fetch_stock_bars(
            ticker=ticker, chart_interval=chart_interval
        )
        events = detect_anomalies(bars, chart_interval)
        logger.info(
            "[DetectAnomalyBars] ticker=%s chart_interval=%s bars=%d anomalies=%d",
            ticker, chart_interval, len(bars), len(events),
        )
        return AnomalyBarsResponse(
            ticker=ticker,
            chart_interval=chart_interval,
            count=len(events),
            events=events,
        )
