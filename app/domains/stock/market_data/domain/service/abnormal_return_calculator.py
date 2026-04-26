"""Abnormal return 계산 — 순수 Domain Service.

(R_stock − R_benchmark) ±N 거래일 누적 차감 수익률. yfinance/DB 응답이 거래일만
포함하므로 캘린더 라이브러리 없이 list slicing으로 거래일 윈도우 추출.

t0 = event_date 가 거래일이 아닌 경우 t0 직후 첫 거래일을 t0 로 간주한다 (공시일이
주말이거나 휴장일에 발생하는 케이스 보정).

INSUFFICIENT_DATA 판정 기준:
- pre_close: t0 이전 마지막 거래일 종가 필수
- post_close: t0 부터 거래일 기준 +post_days 째 거래일 종가 필수
- 둘 중 하나 부재 시 INSUFFICIENT_DATA + 가능한 sample_completeness 만 채움
"""
from datetime import date
from typing import List, Optional, Tuple

from app.domains.stock.market_data.domain.entity.daily_bar import DailyBar
from app.domains.stock.market_data.domain.value_object.abnormal_return_result import (
    AbnormalReturnResult,
)
from app.domains.stock.market_data.domain.value_object.event_impact_status import (
    EventImpactStatus,
)


def _split_around_event(
    bars: List[DailyBar], event_date: date
) -> Tuple[List[DailyBar], List[DailyBar]]:
    """bars (오름차순)를 event_date 직전(<)과 직후(≥)로 분할."""
    pre = [b for b in bars if b.bar_date < event_date]
    post = [b for b in bars if b.bar_date >= event_date]
    return pre, post


def _get_pre_close(bars: List[DailyBar], event_date: date) -> Optional[float]:
    pre, _ = _split_around_event(bars, event_date)
    if not pre:
        return None
    return pre[-1].close


def _get_post_close(
    bars: List[DailyBar], event_date: date, offset_trading_days: int
) -> Optional[float]:
    """event_date 이후 첫 거래일부터 offset_trading_days 째 거래일 종가.

    offset_trading_days=0 이면 event_date 이후 첫 거래일 자체.
    """
    _, post = _split_around_event(bars, event_date)
    if len(post) <= offset_trading_days:
        return None
    return post[offset_trading_days].close


def _safe_pct(curr: Optional[float], base: Optional[float]) -> Optional[float]:
    if curr is None or base is None or base == 0:
        return None
    return (curr / base - 1.0) * 100.0


class AbnormalReturnCalculator:

    @staticmethod
    def compute(
        stock_bars: List[DailyBar],
        benchmark_bars: List[DailyBar],
        event_date: date,
        post_days: int,
    ) -> AbnormalReturnResult:
        """post_days = +5 → 이벤트일 이후 5거래일 후 종가까지 누적 (총 6거래일 윈도우)."""
        if post_days <= 0:
            raise ValueError(f"post_days must be positive: {post_days}")

        if not stock_bars:
            return AbnormalReturnResult(status=EventImpactStatus.STOCK_DATA_MISSING)
        if not benchmark_bars:
            return AbnormalReturnResult(status=EventImpactStatus.BENCHMARK_DATA_MISSING)

        sorted_stock = sorted(stock_bars, key=lambda b: b.bar_date)
        sorted_bench = sorted(benchmark_bars, key=lambda b: b.bar_date)

        # offset_trading_days=N → t0(이벤트 후 첫 거래일)로부터 N거래일 후 종가.
        # post_days=5 → t+5 거래일 종가 (post[5]). pre = t-1.
        offset = post_days

        stock_pre = _get_pre_close(sorted_stock, event_date)
        stock_post = _get_post_close(sorted_stock, event_date, offset)
        bench_pre = _get_pre_close(sorted_bench, event_date)
        bench_post = _get_post_close(sorted_bench, event_date, offset)

        # sample completeness — 4 가지 종가 중 확보된 비율
        present = sum(
            1 for v in (stock_pre, stock_post, bench_pre, bench_post) if v is not None
        )
        completeness = present / 4.0

        if stock_pre is None or stock_post is None:
            return AbnormalReturnResult(
                status=EventImpactStatus.INSUFFICIENT_DATA,
                sample_completeness=completeness,
            )
        if bench_pre is None or bench_post is None:
            return AbnormalReturnResult(
                status=EventImpactStatus.INSUFFICIENT_DATA,
                cumulative_return_pct=_safe_pct(stock_post, stock_pre),
                sample_completeness=completeness,
            )

        r_stock = _safe_pct(stock_post, stock_pre)
        r_bench = _safe_pct(bench_post, bench_pre)
        if r_stock is None or r_bench is None:
            return AbnormalReturnResult(
                status=EventImpactStatus.INSUFFICIENT_DATA,
                cumulative_return_pct=r_stock,
                benchmark_return_pct=r_bench,
                sample_completeness=completeness,
            )

        return AbnormalReturnResult(
            status=EventImpactStatus.OK,
            cumulative_return_pct=round(r_stock, 4),
            benchmark_return_pct=round(r_bench, 4),
            abnormal_return_pct=round(r_stock - r_bench, 4),
            sample_completeness=completeness,
        )
