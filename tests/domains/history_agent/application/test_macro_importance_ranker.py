"""MacroImportanceRanker — LLM mock 점수 할당 + DB 캐시 재사용."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.macro_importance_ranker import (
    MacroImportanceRanker,
)
from app.domains.history_agent.domain.entity.event_enrichment import (
    EventEnrichment,
    compute_detail_hash,
)

pytestmark = pytest.mark.asyncio


def _event(idx: int, event_type: str = "CPI") -> TimelineEvent:
    return TimelineEvent(
        title=f"title-{idx}",
        date=datetime.date(2024, 1, idx + 1),
        category="MACRO",
        type=event_type,
        detail=f"detail-{idx}",
    )


class _FakeLLM:
    def __init__(self, scores: list[float]):
        self._payload = f"{scores}"
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        mock_response = MagicMock()
        mock_response.content = self._payload
        return mock_response


async def test_ranker_applies_llm_scores_and_persists(monkeypatch):
    events = [_event(0), _event(1), _event(2)]
    repo = MagicMock()
    repo.find_by_keys = AsyncMock(return_value=[])
    repo.upsert_bulk = AsyncMock(return_value=3)

    fake_llm = _FakeLLM([0.9, 0.1, 0.55])

    with patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm",
        return_value=fake_llm,
    ):
        ranker = MacroImportanceRanker(enrichment_repo=repo)
        await ranker.score(events)

    assert [round(e.importance_score or 0, 2) for e in events] == [0.9, 0.1, 0.55]
    assert fake_llm.calls == 1
    repo.upsert_bulk.assert_awaited_once()
    saved = repo.upsert_bulk.call_args.args[0]
    assert len(saved) == 3
    assert all(isinstance(row, EventEnrichment) for row in saved)
    assert all(row.importance_score is not None for row in saved)


async def test_ranker_uses_cache_when_available():
    events = [_event(0), _event(1)]
    cached = [
        EventEnrichment(
            ticker="__MACRO__",
            event_date=events[0].date,
            event_type=events[0].type,
            detail_hash=compute_detail_hash(events[0].detail),
            title=events[0].title,
            importance_score=0.88,
        )
    ]
    repo = MagicMock()
    repo.find_by_keys = AsyncMock(return_value=cached)
    repo.upsert_bulk = AsyncMock(return_value=1)

    fake_llm = _FakeLLM([0.44])  # only the miss

    with patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm",
        return_value=fake_llm,
    ):
        ranker = MacroImportanceRanker(enrichment_repo=repo)
        await ranker.score(events)

    assert events[0].importance_score == 0.88  # from cache
    assert round(events[1].importance_score or 0, 2) == 0.44  # from LLM
    assert fake_llm.calls == 1


async def test_ranker_skips_events_with_preassigned_score():
    events = [_event(0), _event(1)]
    events[0].importance_score = 1.0  # curated

    repo = MagicMock()
    repo.find_by_keys = AsyncMock(return_value=[])
    repo.upsert_bulk = AsyncMock(return_value=1)

    fake_llm = _FakeLLM([0.5])

    with patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm",
        return_value=fake_llm,
    ):
        ranker = MacroImportanceRanker(enrichment_repo=repo)
        await ranker.score(events)

    assert events[0].importance_score == 1.0  # untouched
    assert events[1].importance_score == 0.5
    # Only 1 event hit repo
    assert len(repo.find_by_keys.call_args.args[0]) == 1


async def test_ranker_falls_back_to_neutral_on_llm_failure():
    events = [_event(0), _event(1)]
    repo = MagicMock()
    repo.find_by_keys = AsyncMock(return_value=[])
    repo.upsert_bulk = AsyncMock(return_value=2)

    broken_llm = MagicMock()
    broken_llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))

    with patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm",
        return_value=broken_llm,
    ):
        ranker = MacroImportanceRanker(enrichment_repo=repo)
        await ranker.score(events)

    # fallback = 0.3
    assert all(e.importance_score == 0.3 for e in events)
