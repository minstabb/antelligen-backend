"""CPI YoY sanity filter 검증 — 2026-04 품질 리포트 S2-1 픽스."""
from datetime import date

from app.domains.dashboard.application.usecase.get_economic_events_usecase import (
    _CPI_YOY_SANITY_PP,
    _to_cpi_yoy_events,
    _yoy,
)
from app.domains.dashboard.domain.entity.macro_data_point import MacroDataPoint


def _mkp(d: date, v: float) -> MacroDataPoint:
    return MacroDataPoint(date=d, value=v)


def test_yoy_returns_none_for_zero_divisor():
    assert _yoy(10.0, 0.0) is None
    assert _yoy(10.0, 1e-12) is None


def test_yoy_normal_case():
    assert _yoy(110.0, 100.0) == 10.0


def test_cpi_events_drop_insane_yoy():
    # 현재 지수 -50.54, 1년 전 287.63 → yoy = (-50.54 - 287.63) / 287.63 ≈ -117.6%
    # sanity 임계 50%p 초과 → drop
    points = [
        _mkp(date(2006, 5, 1), 287.63),
        _mkp(date(2007, 5, 1), -50.54),
    ]
    events = _to_cpi_yoy_events(points, "CPI", "CPI", start_date=date(2007, 1, 1))
    assert events == []


def test_cpi_events_keep_normal_yoy():
    # 전년 대비 정상적인 3% 상승
    points = [
        _mkp(date(2025, 1, 1), 100.0),
        _mkp(date(2026, 1, 1), 103.0),
    ]
    events = _to_cpi_yoy_events(points, "CPI", "CPI", start_date=date(2025, 6, 1))
    assert len(events) == 1
    assert events[0].value == 3.0
    assert abs(events[0].value) <= _CPI_YOY_SANITY_PP
