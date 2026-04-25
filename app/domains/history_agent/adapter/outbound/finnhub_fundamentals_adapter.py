"""Finnhub recommendation + earnings 를 FundamentalsEventPort 로 변환.

레이팅 데이터는 월별 aggregate — 이전 달과 비교해 buy/sell 비율이 의미 있게 움직인 달만 이벤트로 승격한다.
실적 서프라이즈는 |surprise%| ≥ 2% 만 이벤트로 승격해 노이즈 억제.
"""

import datetime
import logging
from typing import List, Optional

from app.domains.causality_agent.adapter.outbound.external.finnhub_news_client import (
    FinnhubNewsClient,
)
from app.domains.history_agent.application.port.out.fundamentals_event_port import (
    FundamentalEvent,
    FundamentalsEventPort,
)

logger = logging.getLogger(__name__)

_PERIOD_DAYS = {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "5Y": 1825}
_DEFAULT_DAYS = 90
_RATING_SHIFT_MIN_PCT = 10.0  # buy/sell 비율 +/-10%p 이상 변동 시 이벤트
_EARNINGS_SURPRISE_MIN_PCT = 2.0


def _period_start(period: str) -> datetime.date:
    days = _PERIOD_DAYS.get(period.upper(), _DEFAULT_DAYS)
    return datetime.date.today() - datetime.timedelta(days=days)


def _parse_period_date(value: str) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


class FinnhubFundamentalsAdapter(FundamentalsEventPort):
    def __init__(self, client: Optional[FinnhubNewsClient] = None):
        self._client = client or FinnhubNewsClient()

    async def fetch_events(
        self, *, ticker: str, period: str
    ) -> List[FundamentalEvent]:
        start = _period_start(period)
        rating_events = await self._rating_events(ticker, start)
        earnings_events = await self._earnings_events(ticker, start)
        return rating_events + earnings_events

    async def _rating_events(
        self, ticker: str, start: datetime.date
    ) -> List[FundamentalEvent]:
        records = await self._client.get_recommendation_trend(ticker)
        if not records:
            return []

        # period 는 YYYY-MM-DD 문자열 (월초). 오래된 순으로 정렬 후 월간 비율 변동 계산.
        sorted_records = sorted(
            (r for r in records if _parse_period_date(r.get("period", ""))),
            key=lambda r: r["period"],
        )

        events: List[FundamentalEvent] = []
        prev_buy_ratio: Optional[float] = None
        for record in sorted_records:
            d = _parse_period_date(record["period"])
            if d is None or d < start:
                prev_buy_ratio = _buy_ratio(record)
                continue
            buy_ratio = _buy_ratio(record)
            if prev_buy_ratio is not None:
                shift = (buy_ratio - prev_buy_ratio) * 100.0
                if abs(shift) >= _RATING_SHIFT_MIN_PCT:
                    ev_type = "ANALYST_UPGRADE" if shift > 0 else "ANALYST_DOWNGRADE"
                    detail = (
                        f"{ticker} 애널리스트 BUY 비율 {prev_buy_ratio * 100:.0f}% → "
                        f"{buy_ratio * 100:.0f}% (Δ{shift:+.0f}%p)"
                    )
                    events.append(
                        FundamentalEvent(
                            date=d, type=ev_type, detail=detail,  # type: ignore[arg-type]
                            source="finnhub", change_pct=shift,
                        )
                    )
            prev_buy_ratio = buy_ratio
        return events

    async def _earnings_events(
        self, ticker: str, start: datetime.date
    ) -> List[FundamentalEvent]:
        records = await self._client.get_earnings_surprise(ticker)
        if not records:
            return []
        events: List[FundamentalEvent] = []
        for record in records:
            d = _parse_period_date(record.get("period", ""))
            if d is None or d < start:
                continue
            surprise_pct_raw = record.get("surprisePercent")
            if surprise_pct_raw is None:
                continue
            try:
                surprise_pct = float(surprise_pct_raw)
            except (TypeError, ValueError):
                continue
            if abs(surprise_pct) < _EARNINGS_SURPRISE_MIN_PCT:
                continue
            actual = record.get("actual")
            estimate = record.get("estimate")
            direction = "BEAT" if surprise_pct > 0 else "MISS"
            ev_type = f"EARNINGS_{direction}"
            detail = (
                f"{ticker} 실적 서프라이즈 {surprise_pct:+.1f}% "
                f"(actual={actual}, estimate={estimate})"
            )
            events.append(
                FundamentalEvent(
                    date=d, type=ev_type, detail=detail,  # type: ignore[arg-type]
                    source="finnhub", change_pct=surprise_pct,
                )
            )
        return events


def _buy_ratio(record: dict) -> float:
    total = sum(
        float(record.get(k, 0) or 0)
        for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
    )
    if total == 0:
        return 0.0
    buy = float(record.get("strongBuy", 0) or 0) + float(record.get("buy", 0) or 0)
    return buy / total
