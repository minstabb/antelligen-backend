import logging
from datetime import date, timedelta
from typing import Callable, List, Optional

from app.domains.dashboard.application.port.out.nasdaq_repository_port import NasdaqRepositoryPort
from app.domains.dashboard.application.response.nasdaq_bar_response import (
    NasdaqBarResponse,
    NasdaqBarsResponse,
)
from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# period별 설정
#   days_back  : DB 조회 시작일 (오늘 기준)
#   max_bars   : 반환할 최대 봉 개수
#   key_fn     : None → 일봉 그대로, 함수 → 집계 기준 bar_date 반환
# ─────────────────────────────────────────
_PERIOD_CONFIG: dict[str, dict] = {
    "1D": {"key_fn": None},
    "1W": {"key_fn": "week"},
    "1M": {"key_fn": "month"},
    "1Y": {"key_fn": "year"},
}


def _week_key(d: date) -> date:
    """해당 날짜가 속한 주의 월요일"""
    return d - timedelta(days=d.weekday())


def _month_key(d: date) -> date:
    """해당 날짜가 속한 월의 1일"""
    return date(d.year, d.month, 1)


def _year_key(d: date) -> date:
    """해당 날짜가 속한 연도의 1월 1일"""
    return date(d.year, 1, 1)


_KEY_FN_MAP: dict[str, Callable[[date], date]] = {
    "week": _week_key,
    "month": _month_key,
    "year": _year_key,
}


def _aggregate(daily_bars: List[NasdaqBar], key_fn: Callable[[date], date]) -> List[NasdaqBar]:
    """일봉 리스트를 key_fn 기준으로 그룹핑해 OHLCV 집계 봉을 반환한다.

    집계 규칙:
        open   = 기간 첫 거래일 시가
        high   = 기간 최고가
        low    = 기간 최저가
        close  = 기간 마지막 거래일 종가
        volume = 기간 합산 거래량
        bar_date = key_fn이 반환하는 기준일 (월요일 / 1일 / 1월 1일)
    """
    groups: dict[date, List[NasdaqBar]] = {}
    for bar in daily_bars:            # daily_bars는 날짜 오름차순
        key = key_fn(bar.bar_date)
        groups.setdefault(key, []).append(bar)

    aggregated: List[NasdaqBar] = []
    for key in sorted(groups):
        group = groups[key]
        aggregated.append(
            NasdaqBar(
                bar_date=key,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )
    return aggregated


class GetNasdaqBarsUseCase:

    def __init__(self, nasdaq_repository: NasdaqRepositoryPort):
        self._nasdaq_repository = nasdaq_repository

    async def execute(self, period: str) -> NasdaqBarsResponse:
        """period 기준 봉 개수로 나스닥 OHLCV 데이터를 반환한다.

        period별 반환 봉 개수:
            1D → 최근 252 일봉
            1W → 최근 156 주봉 (bar_date = 해당 주 월요일)
            1M → 최근  60 월봉 (bar_date = 해당 월 1일)
            1Y → 최근  20 연봉 (bar_date = 해당 연도 1월 1일)
        """
        key_fn_name: Optional[str] = _PERIOD_CONFIG[period]["key_fn"]

        daily_bars = await self._nasdaq_repository.find_by_date_range(
            start=date(1971, 1, 1), end=date.today()
        )

        if key_fn_name is None:
            bars = daily_bars
        else:
            bars = _aggregate(daily_bars, _KEY_FN_MAP[key_fn_name])

        logger.info(
            "[GetNasdaqBars] period=%s, fetched=%d, returned=%d",
            period,
            len(daily_bars),
            len(bars),
        )

        return NasdaqBarsResponse(
            period=period,
            count=len(bars),
            bars=[NasdaqBarResponse.from_entity(bar) for bar in bars],
        )
