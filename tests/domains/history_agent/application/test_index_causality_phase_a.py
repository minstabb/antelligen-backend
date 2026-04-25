"""T2-1 Phase A: INDEX causality 규칙 기반 매핑 테스트."""

import datetime

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _infer_rule_based_index_causality,
)


_DATE = datetime.date(2024, 9, 18)


def _price(change_pct: float) -> TimelineEvent:
    return TimelineEvent(
        title="급등",
        date=_DATE,
        category="PRICE",
        type="SURGE",
        detail="x",
        change_pct=change_pct,
    )


def _macro(day_offset: int, event_type: str, change_pct: float, label: str) -> TimelineEvent:
    return TimelineEvent(
        title=label,
        date=_DATE + datetime.timedelta(days=day_offset),
        category="MACRO",
        type=event_type,
        detail="x",
        change_pct=change_pct,
    )


def test_rule_based_maps_macro_within_window():
    price_event = _price(2.1)
    macro_events = [_macro(0, "INTEREST_RATE", -0.5, "기준금리")]

    hypotheses = _infer_rule_based_index_causality(price_event, macro_events)

    assert len(hypotheses) == 1
    assert "기준금리" in hypotheses[0].hypothesis
    assert "하락" in hypotheses[0].hypothesis
    assert hypotheses[0].supporting_tools_called == ["fred:rule_based"]


def test_rule_based_skips_macro_outside_window():
    price_event = _price(2.1)
    # -5일은 기본 윈도우(-3일) 밖
    macro_events = [_macro(-5, "CPI", 0.3, "CPI")]

    hypotheses = _infer_rule_based_index_causality(price_event, macro_events)

    assert hypotheses == []


def test_rule_based_multiple_macro_events_all_mapped():
    price_event = _price(-3.0)
    macro_events = [
        _macro(-1, "INTEREST_RATE", 0.25, "기준금리"),
        _macro(0, "CPI", 0.4, "CPI"),
    ]

    hypotheses = _infer_rule_based_index_causality(price_event, macro_events)

    assert len(hypotheses) == 2


def test_rule_based_empty_when_no_macro():
    assert _infer_rule_based_index_causality(_price(1.5), []) == []


def test_rule_based_handles_zero_change_as_flat():
    price_event = _price(1.0)
    macro_events = [_macro(0, "INTEREST_RATE", 0.0, "기준금리")]
    hypotheses = _infer_rule_based_index_causality(price_event, macro_events)
    assert len(hypotheses) == 1
    assert "동결" in hypotheses[0].hypothesis
