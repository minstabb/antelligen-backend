"""
_enrich_causality 단위 테스트.

run_causality_agent를 mock으로 대체하므로 외부 API 없이 즉시 실행된다.
"""
import asyncio
import datetime
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio

from app.domains.history_agent.application.response.timeline_response import (
    HypothesisResult,
    TimelineEvent,
    TimelineResponse,
)
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _CAUSALITY_TRIGGER_TYPES,
    _MAX_CAUSALITY_EVENTS,
    _enrich_causality,
)

_MOCK_HYPOTHESES = [
    {
        "hypothesis": "연준 금리 동결 → 기술주 급등",
        "supporting_tools_called": ["get_fred_series", "get_price_stats"],
    }
]


def _make_event(event_type: str, days_ago: int = 10) -> TimelineEvent:
    return TimelineEvent(
        title=event_type,
        date=datetime.date.today() - datetime.timedelta(days=days_ago),
        category="PRICE",
        type=event_type,
        detail=f"{event_type} 이벤트",
    )


# ─────────────────────────────────────────────────────────────
# 트리거 조건 검증
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_surge_event_gets_causality():
    """SURGE 이벤트에 causality가 주입된다."""
    timeline = [_make_event("SURGE")]

    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._run_causality",
        new_callable=AsyncMock,
        return_value=[HypothesisResult(**h) for h in _MOCK_HYPOTHESES],
    ):
        await _enrich_causality("AAPL", timeline)

    assert timeline[0].causality is not None
    assert len(timeline[0].causality) == 1
    assert "연준" in timeline[0].causality[0].hypothesis


@pytest.mark.asyncio
async def test_plunge_event_gets_causality():
    """PLUNGE 이벤트에 causality가 주입된다."""
    timeline = [_make_event("PLUNGE")]

    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._run_causality",
        new_callable=AsyncMock,
        return_value=[HypothesisResult(**h) for h in _MOCK_HYPOTHESES],
    ):
        await _enrich_causality("AAPL", timeline)

    assert timeline[0].causality is not None



@pytest.mark.asyncio
async def test_non_trigger_events_skip_causality():
    """HIGH_52W, LOW_52W, GAP_UP, GAP_DOWN은 causality 분석을 건너뛴다."""
    non_trigger_types = ["HIGH_52W", "LOW_52W", "GAP_UP", "GAP_DOWN"]
    timeline = [_make_event(t, days_ago=i + 1) for i, t in enumerate(non_trigger_types)]

    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._run_causality",
        new_callable=AsyncMock,
    ) as mock_run:
        await _enrich_causality("AAPL", timeline)
        mock_run.assert_not_called()

    assert all(e.causality is None for e in timeline)


# ─────────────────────────────────────────────────────────────
# 최대 개수 제한
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_max_causality_events_cap():
    """_MAX_CAUSALITY_EVENTS 개수만큼만 분석을 호출한다."""
    timeline = [_make_event("SURGE", days_ago=i + 1) for i in range(_MAX_CAUSALITY_EVENTS + 2)]

    call_count = 0

    async def mock_run(ticker, event):
        nonlocal call_count
        call_count += 1
        return [HypothesisResult(**h) for h in _MOCK_HYPOTHESES]

    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._run_causality",
        side_effect=mock_run,
    ):
        await _enrich_causality("AAPL", timeline)

    assert call_count == _MAX_CAUSALITY_EVENTS


# ─────────────────────────────────────────────────────────────
# Graceful fallback
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_causality_failure_leaves_field_none():
    """_run_causality가 예외를 던지면 causality 필드가 None으로 유지된다."""
    timeline = [_make_event("SURGE")]

    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._run_causality",
        new_callable=AsyncMock,
        side_effect=Exception("Anthropic API 오류"),
    ):
        await _enrich_causality("AAPL", timeline)

    assert timeline[0].causality is None


@pytest.mark.asyncio
async def test_partial_failure_does_not_block_other_events():
    """첫 번째 이벤트 실패가 두 번째 이벤트 성공을 막지 않는다."""
    timeline = [_make_event("SURGE", 1), _make_event("PLUNGE", 2)]
    results = [
        Exception("첫 번째 실패"),
        [HypothesisResult(**h) for h in _MOCK_HYPOTHESES],
    ]

    async def mock_run(ticker, event):
        return results.pop(0)

    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._run_causality",
        side_effect=mock_run,
    ):
        await _enrich_causality("AAPL", timeline)

    assert timeline[0].causality is None      # 실패 → None
    assert timeline[1].causality is not None  # 성공 → 주입됨


# ─────────────────────────────────────────────────────────────
# 직렬화 검증
# ─────────────────────────────────────────────────────────────

def test_timeline_event_serializes_causality():
    """causality 필드가 JSON으로 올바르게 직렬화된다."""
    event = TimelineEvent(
        title="급등",
        date=datetime.date(2024, 3, 15),
        category="PRICE",
        type="SURGE",
        detail="+6.2% 급등",
        causality=[
            HypothesisResult(
                hypothesis="연준 금리 동결 → 기술주 급등",
                supporting_tools_called=["get_fred_series"],
            )
        ],
    )
    dumped = event.model_dump()
    assert dumped["title"] == "급등"
    assert dumped["causality"][0]["hypothesis"] == "연준 금리 동결 → 기술주 급등"
    assert "get_fred_series" in dumped["causality"][0]["supporting_tools_called"]


def test_timeline_event_causality_none_by_default():
    """causality 필드는 기본적으로 None이다."""
    event = TimelineEvent(
        title="52주 신고가",
        date=datetime.date(2024, 3, 15),
        category="PRICE",
        type="HIGH_52W",
        detail="52주 신고가",
    )
    assert event.causality is None
    dumped = event.model_dump()
    assert dumped["causality"] is None
