import asyncio
import logging
from datetime import date, timedelta
from typing import List

from app.domains.dashboard.application.port.out.fred_macro_port import FredMacroPort
from app.domains.dashboard.application.response.economic_event_response import (
    EconomicEventResponse,
    EconomicEventsResponse,
)
from app.domains.dashboard.domain.entity.economic_event import EconomicEvent
from app.domains.dashboard.domain.entity.macro_data_point import MacroDataPoint

logger = logging.getLogger(__name__)

_PERIOD_TO_DAYS: dict[str, int] = {
    "1D": 365,
    "1W": 1_095,
    "1M": 1_825,
    "1Y": 7_300,
}

# series_id → (event_type, label, apply_yoy)
# apply_yoy=True: 원지수(index level) → 전년 동월 대비 변화율(%) 변환 필요
_SERIES_CONFIG: dict[str, tuple[str, str, bool]] = {
    # US
    "FEDFUNDS":     ("INTEREST_RATE", "기준금리", False),
    "CPIAUCSL":     ("CPI", "CPI", True),
    "UNRATE":       ("UNEMPLOYMENT", "실업률", False),
    # KR — FRED OECD/BOK 시리즈
    "INTDSRKRM193N":    ("INTEREST_RATE", "기준금리 (BOK)", False),
    "CPALTT01KRM657N":  ("CPI", "CPI (한국)", True),   # OECD CPI index → YoY
    "LRHUTTTTKRIQ156S": ("UNEMPLOYMENT", "실업률 (한국)", False),
    # TODO: 글로벌 공통 이벤트(유가 WTISPLC 등) 필요 시 "GLOBAL" 리전 추가
}

_REGION_SERIES: dict[str, list[str]] = {
    "US": ["FEDFUNDS", "CPIAUCSL", "UNRATE"],
    "KR": ["INTDSRKRM193N", "CPALTT01KRM657N", "LRHUTTTTKRIQ156S"],
}

_DEFAULT_REGION = "US"


def _to_events(
    full_data: List[MacroDataPoint],
    event_type: str,
    label: str,
    start_date: date,
) -> List[EconomicEvent]:
    """전체 시리즈에서 start_date 이후 데이터만 이벤트로 변환한다.

    previous는 full_data 기준 직전 인덱스 값을 사용해
    필터링 경계에서도 정확한 이전 발표값을 반환한다.
    """
    events: List[EconomicEvent] = []
    for i, point in enumerate(full_data):
        if point.date < start_date:
            continue
        previous = full_data[i - 1].value if i > 0 else None
        events.append(
            EconomicEvent(
                event_id=f"{event_type}-{point.date.strftime('%Y-%m-%d')}",
                type=event_type,
                label=label,
                date=point.date,
                value=point.value,
                previous=previous,
                forecast=None,
            )
        )
    return events


def _yoy(current: float, year_ago: float) -> float:
    return round((current - year_ago) / year_ago * 100, 2)


def _to_cpi_yoy_events(
    full_data: List[MacroDataPoint],
    event_type: str,
    label: str,
    start_date: date,
) -> List[EconomicEvent]:
    """CPI 원지수 데이터를 전년 동월 대비 변화율(%)로 변환한다.

    계산식: (현재 지수 - 1년 전 지수) / 1년 전 지수 × 100
    전년 동월 값이 없는 포인트는 건너뛴다.
    """
    date_to_value = {p.date: p.value for p in full_data}

    events: List[EconomicEvent] = []
    for i, point in enumerate(full_data):
        if point.date < start_date:
            continue

        year_ago_date = point.date.replace(year=point.date.year - 1)
        year_ago_value = date_to_value.get(year_ago_date)
        if not year_ago_value:
            continue

        previous_yoy: float | None = None
        if i > 0:
            prev = full_data[i - 1]
            prev_year_ago_date = prev.date.replace(year=prev.date.year - 1)
            prev_year_ago_value = date_to_value.get(prev_year_ago_date)
            if prev_year_ago_value:
                previous_yoy = _yoy(prev.value, prev_year_ago_value)

        events.append(
            EconomicEvent(
                event_id=f"{event_type}-{point.date.strftime('%Y-%m-%d')}",
                type=event_type,
                label=label,
                date=point.date,
                value=_yoy(point.value, year_ago_value),
                previous=previous_yoy,
                forecast=None,
            )
        )
    return events


class GetEconomicEventsUseCase:

    def __init__(self, fred_macro_port: FredMacroPort):
        self._fred = fred_macro_port

    async def execute(self, period: str, region: str = _DEFAULT_REGION) -> EconomicEventsResponse:
        """period + region 기준 경제 이벤트 목록을 반환한다.

        Args:
            period: "1D" | "1W" | "1M" | "1Y"
            region: "US" | "KR" (미지원 region은 US로 fallback)

        Returns:
            EconomicEventsResponse — 시리즈별 실패는 로그 후 건너뜀 (graceful degradation)
        """
        series_ids = _REGION_SERIES.get(region, _REGION_SERIES[_DEFAULT_REGION])

        days = _PERIOD_TO_DAYS[period]
        start_date = date.today() - timedelta(days=days)
        base_months = days // 30 + 2  # previous 값 확보용 여유

        tasks = [
            self._fred.fetch_series(
                sid,
                base_months + (12 if _SERIES_CONFIG[sid][2] else 0),  # YoY용 +12개월
            )
            for sid in series_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_events: List[EconomicEvent] = []
        for sid, data in zip(series_ids, results):
            if isinstance(data, Exception):
                logger.warning(
                    "[GetEconomicEvents] 시리즈 조회 실패 (graceful degradation): series=%s, error=%s",
                    sid, data,
                )
                continue
            event_type, label, apply_yoy = _SERIES_CONFIG[sid]
            if apply_yoy:
                all_events.extend(_to_cpi_yoy_events(data, event_type, label, start_date))
            else:
                all_events.extend(_to_events(data, event_type, label, start_date))

        all_events.sort(key=lambda e: e.date)

        logger.info(
            "[GetEconomicEvents] 완료: period=%s, region=%s, total_events=%d",
            period, region, len(all_events),
        )

        return EconomicEventsResponse(
            period=period,
            count=len(all_events),
            events=[EconomicEventResponse.from_entity(e) for e in all_events],
        )
