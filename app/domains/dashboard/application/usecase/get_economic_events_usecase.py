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
    "1Q": 7_300,
    "1Y": 7_300,
}

# series_id → (event_type, label, apply_yoy, fallback_title)
# apply_yoy=True: 원지수(index level) → 전년 동월 대비 변화율(%) 변환 필요
# fallback_title: LLM 타이틀 생성 실패 시 노출할 짧은 한국어 타이틀 (단일 소스)
_SERIES_CONFIG: dict[str, tuple[str, str, bool, str]] = {
    # US
    "FEDFUNDS":     ("INTEREST_RATE", "기준금리", False, "기준금리 결정"),
    "CPIAUCSL":     ("CPI", "CPI", True, "CPI 발표"),
    "UNRATE":       ("UNEMPLOYMENT", "실업률", False, "실업률 발표"),
    # KR — FRED OECD/BOK 시리즈
    # 2026-04 §17 결정: CPALTT01KRM657N(MoM 성장률)에 apply_yoy=True 를 걸면
    # 성장률의 YoY를 재계산하는 것이 되어 ±수백% 독성값 발생.
    # KORCPIALLMINMEI(원지수, 2010=100) 로 교체. apply_yoy=True 유지해 정상 YoY %.
    # 실업률: LRHUTTTTKRIQ156S(분기, Q)는 미지원 ID로 FRED 400. M(월간) 으로 교체.
    "INTDSRKRM193N":    ("INTEREST_RATE", "기준금리 (BOK)", False, "한국 기준금리"),
    "KORCPIALLMINMEI":  ("CPI", "CPI (한국)", True, "한국 CPI 발표"),   # OECD CPI index → YoY
    "LRHUTTTTKRM156S":  ("UNEMPLOYMENT", "실업률 (한국)", False, "한국 실업률"),
    # TODO: 글로벌 공통 이벤트(유가 WTISPLC 등) 필요 시 "GLOBAL" 리전 추가
}


def macro_fallback_titles() -> dict[str, str]:
    """_SERIES_CONFIG에서 event_type → fallback_title 매핑을 파생한다.

    같은 event_type을 여러 리전이 공유하는 경우(예: INTEREST_RATE) US가 덮어쓰지 않도록
    최초 등록 값을 유지하되, 동일 event_type은 리전-불문 fallback으로 사용된다.
    """
    result: dict[str, str] = {}
    for event_type, _, _, fallback in _SERIES_CONFIG.values():
        result.setdefault(event_type, fallback)
    return result


_REGION_SERIES: dict[str, list[str]] = {
    "US": ["FEDFUNDS", "CPIAUCSL", "UNRATE"],
    "KR": ["INTDSRKRM193N", "KORCPIALLMINMEI", "LRHUTTTTKRM156S"],
}

_DEFAULT_REGION = "US"

# event_type → "이전 대비 의미 있는 변화"로 간주할 절대 임계치
# CPI/UNEMPLOYMENT는 %p(퍼센트 포인트), INTEREST_RATE는 %p(≈ 25bp=0.25).
_SURPRISE_THRESHOLDS: dict[str, float] = {
    "CPI": 0.3,
    "UNEMPLOYMENT": 0.2,
    "INTEREST_RATE": 0.25,
}

# CPI YoY는 역사상 ±30%p 범위 내. |yoy| > 50%p 는 시리즈·계산 아티팩트로 간주해 버린다.
# 2026-04 품질 리포트에서 KR CPI 시리즈가 -338%p / +289%p 노출된 사례가 발단.
_CPI_YOY_SANITY_PP: float = 50.0


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


def _yoy(current: float, year_ago: float) -> float | None:
    if year_ago == 0 or abs(year_ago) < 1e-9:
        return None
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

        current_yoy = _yoy(point.value, year_ago_value)
        if current_yoy is None or abs(current_yoy) > _CPI_YOY_SANITY_PP:
            continue

        previous_yoy: float | None = None
        if i > 0:
            prev = full_data[i - 1]
            prev_year_ago_date = prev.date.replace(year=prev.date.year - 1)
            prev_year_ago_value = date_to_value.get(prev_year_ago_date)
            if prev_year_ago_value:
                candidate = _yoy(prev.value, prev_year_ago_value)
                if candidate is not None and abs(candidate) <= _CPI_YOY_SANITY_PP:
                    previous_yoy = candidate

        events.append(
            EconomicEvent(
                event_id=f"{event_type}-{point.date.strftime('%Y-%m-%d')}",
                type=event_type,
                label=label,
                date=point.date,
                value=current_yoy,
                previous=previous_yoy,
                forecast=None,
            )
        )
    return events


def _is_surprise(event: EconomicEvent, thresholds: dict[str, float]) -> bool:
    """previous 대비 변화량 절대값이 type별 임계치 이상일 때만 True."""
    if event.previous is None:
        return False
    threshold = thresholds.get(event.type)
    if threshold is None:
        return True
    return abs(event.value - event.previous) >= threshold


class GetEconomicEventsUseCase:

    def __init__(self, fred_macro_port: FredMacroPort):
        self._fred = fred_macro_port

    async def execute(
        self,
        period: str,
        region: str = _DEFAULT_REGION,
        *,
        surprise_only: bool = False,
        surprise_thresholds: dict[str, float] | None = None,
    ) -> EconomicEventsResponse:
        """period + region 기준 경제 이벤트 목록을 반환한다.

        Args:
            period: "1D" | "1W" | "1M" | "1Y"
            region: "US" | "KR" (미지원 region은 US로 fallback)
            surprise_only: True면 _SURPRISE_THRESHOLDS 이상의 변화만 반환
            surprise_thresholds: type별 임계치 override (미지정 시 _SURPRISE_THRESHOLDS)

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
            event_type, label, apply_yoy, _ = _SERIES_CONFIG[sid]
            if apply_yoy:
                all_events.extend(_to_cpi_yoy_events(data, event_type, label, start_date))
            else:
                all_events.extend(_to_events(data, event_type, label, start_date))

        all_events.sort(key=lambda e: e.date)

        if surprise_only:
            thresholds = surprise_thresholds or _SURPRISE_THRESHOLDS
            before = len(all_events)
            all_events = [e for e in all_events if _is_surprise(e, thresholds)]
            logger.info(
                "[GetEconomicEvents] surprise 필터: %d → %d (region=%s)",
                before, len(all_events), region,
            )

        logger.info(
            "[GetEconomicEvents] 완료: period=%s, region=%s, total_events=%d",
            period, region, len(all_events),
        )

        return EconomicEventsResponse(
            period=period,
            count=len(all_events),
            events=[EconomicEventResponse.from_entity(e) for e in all_events],
        )
