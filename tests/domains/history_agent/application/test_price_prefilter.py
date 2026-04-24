"""
PRICE 이벤트 Pre-filter 단위 테스트.

_from_price_events의 change_pct 전파,
_price_importance 우선순위,
_enrich_price_titles 의 LLM/rule-based 분할을 검증한다.
"""
import datetime
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.dashboard.application.response.price_event_response import (
    PriceEventResponse,
    PriceEventsResponse,
)
from app.domains.history_agent.application.response.timeline_response import (
    HypothesisResult,
    TimelineEvent,
)
from app.domains.history_agent.application.service.title_generation_service import (
    FALLBACK_TITLE as _FALLBACK_TITLE,
    PRICE_LLM_TOP_N as _PRICE_LLM_TOP_N,
    enrich_price_titles as _enrich_price_titles,
    price_importance as _price_importance,
    rule_based_price_title as _rule_based_price_title,
)
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _from_price_events,
)

_TODAY = datetime.date.today()


def _pr(event_type: str, value: float, day_offset: int = 0) -> PriceEventResponse:
    return PriceEventResponse(
        date=_TODAY - datetime.timedelta(days=day_offset),
        type=event_type,
        value=value,
        detail=f"{event_type} {value:+.2f}%",
    )


# ─────────────────────────────────────────────────────────────
# _from_price_events: change_pct 전파
# ─────────────────────────────────────────────────────────────

def test_from_price_events_sets_change_pct_for_pct_types():
    """SURGE/PLUNGE/GAP_UP/GAP_DOWN은 value를 change_pct로 세팅한다."""
    resp = PriceEventsResponse(
        ticker="AAPL",
        period="1M",
        count=4,
        events=[
            _pr("SURGE", 7.25, 1),
            _pr("PLUNGE", -5.80, 2),
            _pr("GAP_UP", 3.10, 3),
            _pr("GAP_DOWN", -2.40, 4),
        ],
    )
    events = _from_price_events(resp)
    assert [e.change_pct for e in events] == [7.25, -5.80, 3.10, -2.40]


def test_from_price_events_no_change_pct_for_52w_and_excludes_high_52w():
    """LOW_52W는 value가 가격이므로 change_pct=None; HIGH_52W는 아예 제외."""
    resp = PriceEventsResponse(
        ticker="AAPL",
        period="1Y",
        count=2,
        events=[
            _pr("HIGH_52W", 250.10, 1),
            _pr("LOW_52W", 120.55, 2),
        ],
    )
    events = _from_price_events(resp)
    assert len(events) == 1
    assert events[0].type == "LOW_52W"
    assert events[0].change_pct is None


# ─────────────────────────────────────────────────────────────
# _price_importance: 우선순위 정렬
# ─────────────────────────────────────────────────────────────

def _te(event_type: str, change_pct=None, with_causality=False) -> TimelineEvent:
    ev = TimelineEvent(
        title=_FALLBACK_TITLE.get(event_type, event_type),
        date=_TODAY,
        category="PRICE",
        type=event_type,
        detail="x",
        change_pct=change_pct,
    )
    if with_causality:
        ev.causality = [HypothesisResult(hypothesis="h", supporting_tools_called=[])]
    return ev


def test_price_importance_causality_beats_large_move():
    """인과가설 붙은 이벤트는 +100 가산 → 큰 변화율 단독보다 우선."""
    surge_with_causality = _te("SURGE", change_pct=5.0, with_causality=True)
    big_gap = _te("GAP_UP", change_pct=9.0)
    assert _price_importance(surge_with_causality) > _price_importance(big_gap)


def test_price_importance_surge_plunge_above_gap():
    """동일 change_pct에서 SURGE/PLUNGE가 GAP보다 상위."""
    surge = _te("SURGE", change_pct=5.0)
    gap_up = _te("GAP_UP", change_pct=5.0)
    assert _price_importance(surge) > _price_importance(gap_up)


# ─────────────────────────────────────────────────────────────
# _rule_based_price_title
# ─────────────────────────────────────────────────────────────

def test_rule_based_price_title_formats_change_pct():
    event = _te("SURGE", change_pct=7.26)
    assert _rule_based_price_title(event) == "급등 (+7.3%)"


def test_rule_based_price_title_negative_sign():
    event = _te("PLUNGE", change_pct=-5.8)
    assert _rule_based_price_title(event) == "급락 (-5.8%)"


def test_rule_based_price_title_no_change_pct_falls_back_to_kind():
    event = _te("LOW_52W", change_pct=None)
    assert _rule_based_price_title(event) == "52주 신저가"


# ─────────────────────────────────────────────────────────────
# _enrich_price_titles: LLM top N, 나머지 rule-based
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_price_titles_splits_into_llm_and_rule_based():
    """
    (_PRICE_LLM_TOP_N + 10) 건의 fallback PRICE 이벤트를 투입하면
    정확히 _PRICE_LLM_TOP_N 건만 LLM, 나머지는 rule-based로 처리된다.
    """
    total = _PRICE_LLM_TOP_N + 10
    # change_pct를 고르게 퍼뜨려 정렬 결정력 확보
    events: List[TimelineEvent] = [
        _te("SURGE", change_pct=float(total - i)) for i in range(total)
    ]

    async def fake_batch_titles(targets, system_prompt, build_line):
        return [f"LLM-{i}" for i in range(len(targets))]

    with patch(
        "app.domains.history_agent.application.service.title_generation_service.batch_titles",
        new=AsyncMock(side_effect=fake_batch_titles),
    ) as mock_batch:
        await _enrich_price_titles(events)
        mock_batch.assert_called_once()
        llm_targets_passed = mock_batch.call_args.args[0]
        assert len(llm_targets_passed) == _PRICE_LLM_TOP_N

    llm_titles = [e.title for e in events if e.title.startswith("LLM-")]
    rule_titles = [e.title for e in events if e.title.startswith("급등 (")]
    assert len(llm_titles) == _PRICE_LLM_TOP_N
    assert len(rule_titles) == total - _PRICE_LLM_TOP_N


@pytest.mark.asyncio
async def test_enrich_price_titles_prioritizes_causality_over_raw_change():
    """인과가설 붙은 약한 SURGE가 인과 없는 강한 GAP보다 먼저 LLM으로 간다."""
    high_gap = _te("GAP_UP", change_pct=12.0)
    weak_surge_causal = _te("SURGE", change_pct=1.0, with_causality=True)
    events = [high_gap, weak_surge_causal]

    captured: List[TimelineEvent] = []

    async def fake_batch_titles(targets, system_prompt, build_line):
        captured.extend(targets)
        return [f"LLM-{i}" for i in range(len(targets))]

    with patch(
        "app.domains.history_agent.application.service.title_generation_service.PRICE_LLM_TOP_N",
        1,
    ):
        with patch(
            "app.domains.history_agent.application.service.title_generation_service.batch_titles",
            new=AsyncMock(side_effect=fake_batch_titles),
        ):
            await _enrich_price_titles(events)

    assert len(captured) == 1
    assert captured[0] is weak_surge_causal


@pytest.mark.asyncio
async def test_enrich_price_titles_skips_already_enriched():
    """_is_fallback_title이 아니면(이미 enrich 완료) 재처리하지 않는다."""
    enriched = _te("SURGE", change_pct=10.0)
    enriched.title = "이미 생성된 타이틀"
    fallback = _te("SURGE", change_pct=1.0)

    events = [enriched, fallback]

    async def fake_batch_titles(targets, system_prompt, build_line):
        return ["LLM-new"] * len(targets)

    with patch(
        "app.domains.history_agent.application.service.title_generation_service.batch_titles",
        new=AsyncMock(side_effect=fake_batch_titles),
    ) as mock_batch:
        await _enrich_price_titles(events)
        targets_passed = mock_batch.call_args.args[0]
        assert len(targets_passed) == 1
        assert targets_passed[0] is fallback

    assert enriched.title == "이미 생성된 타이틀"
