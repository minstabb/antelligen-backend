from typing import List

from app.domains.dashboard.domain.entity.price_event import PriceEvent, PriceEventType
from app.domains.dashboard.domain.entity.stock_bar import StockBar

# 감지 임계값
_PRICE_CHANGE_THRESHOLD = 5.0   # ±5% 등락
_GAP_THRESHOLD = 2.0            # 갭 상승/하락 2%
_52W_WINDOW = 252               # 52주 거래일


class PriceEventCollector:
    """일봉 OHLCV 리스트에서 유의미한 가격 이벤트를 감지하는 도메인 서비스."""

    def collect(self, bars: List[StockBar]) -> List[PriceEvent]:
        """bars는 날짜 오름차순 정렬된 일봉 리스트여야 한다."""
        if len(bars) < 2:
            return []

        events: List[PriceEvent] = []
        events.extend(self._detect_52w(bars))
        events.extend(self._detect_price_change(bars))
        events.extend(self._detect_gap(bars))

        events.sort(key=lambda e: e.date)
        return events

    # ── 52주 신고가 / 신저가 ──────────────────────────────────────────────

    @staticmethod
    def _detect_52w(bars: List[StockBar]) -> List[PriceEvent]:
        events: List[PriceEvent] = []
        for i in range(_52W_WINDOW, len(bars)):
            window = bars[i - _52W_WINDOW:i]
            current_close = bars[i].close
            window_high = max(b.close for b in window)
            window_low = min(b.close for b in window)

            if current_close > window_high:
                events.append(PriceEvent(
                    date=bars[i].bar_date,
                    type=PriceEventType.HIGH_52W,
                    value=round(current_close, 2),
                    detail=f"52주 신고가: {current_close:.2f}",
                ))
            elif current_close < window_low:
                events.append(PriceEvent(
                    date=bars[i].bar_date,
                    type=PriceEventType.LOW_52W,
                    value=round(current_close, 2),
                    detail=f"52주 신저가: {current_close:.2f}",
                ))
        return events

    # ── ±5% 등락 ─────────────────────────────────────────────────────────

    @staticmethod
    def _detect_price_change(bars: List[StockBar]) -> List[PriceEvent]:
        events: List[PriceEvent] = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            if prev_close == 0:
                continue
            change_pct = (bars[i].close - prev_close) / prev_close * 100

            if change_pct >= _PRICE_CHANGE_THRESHOLD:
                events.append(PriceEvent(
                    date=bars[i].bar_date,
                    type=PriceEventType.SURGE,
                    value=round(change_pct, 2),
                    detail=f"급등 +{change_pct:.2f}%",
                ))
            elif change_pct <= -_PRICE_CHANGE_THRESHOLD:
                events.append(PriceEvent(
                    date=bars[i].bar_date,
                    type=PriceEventType.PLUNGE,
                    value=round(change_pct, 2),
                    detail=f"급락 {change_pct:.2f}%",
                ))
        return events

    # ── 갭 상승 / 하락 ────────────────────────────────────────────────────

    @staticmethod
    def _detect_gap(bars: List[StockBar]) -> List[PriceEvent]:
        events: List[PriceEvent] = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            if prev_close == 0:
                continue
            gap_pct = (bars[i].open - prev_close) / prev_close * 100

            if gap_pct >= _GAP_THRESHOLD:
                events.append(PriceEvent(
                    date=bars[i].bar_date,
                    type=PriceEventType.GAP_UP,
                    value=round(gap_pct, 2),
                    detail=f"갭 상승 +{gap_pct:.2f}%",
                ))
            elif gap_pct <= -_GAP_THRESHOLD:
                events.append(PriceEvent(
                    date=bars[i].bar_date,
                    type=PriceEventType.GAP_DOWN,
                    value=round(gap_pct, 2),
                    detail=f"갭 하락 {gap_pct:.2f}%",
                ))
        return events
