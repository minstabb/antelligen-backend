"""S3-1 / §13.4 B follow-up: NEWS 영문 제목 한국어 1문장 요약 (batch_titles 경로)."""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _enrich_news_details,
)


def _make_news(title: str) -> TimelineEvent:
    return TimelineEvent(
        title=title,
        date=date(2026, 4, 21),
        category="NEWS",
        type="NEWS",
        detail=title,
        source="news:finnhub",
    )


@pytest.mark.asyncio
async def test_enrich_news_replaces_english_headline():
    """영문 제목(200자 이상 또는 순수 영문)에 대해 title/detail 동시 교체."""
    events = [
        _make_news(
            "Apple's post-Cook future hinges on whether Ternus can ignite AI growth"
        ),
    ]
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase.batch_titles",
        new=AsyncMock(return_value=["애플, 쿡 이후 AI 성장 리더십 쟁점"]),
    ):
        await _enrich_news_details(events)

    assert events[0].title == "애플, 쿡 이후 AI 성장 리더십 쟁점"
    assert events[0].detail == "애플, 쿡 이후 AI 성장 리더십 쟁점"


@pytest.mark.asyncio
async def test_enrich_news_skips_korean_headline():
    """이미 한국어 제목은 LLM 호출 없이 건너뛴다."""
    events = [_make_news("삼성전자, 신형 HBM 양산 돌입")]
    mock = AsyncMock()
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase.batch_titles",
        new=mock,
    ):
        await _enrich_news_details(events)
    mock.assert_not_called()
    assert events[0].title == "삼성전자, 신형 HBM 양산 돌입"


@pytest.mark.asyncio
async def test_enrich_news_feature_flag_off_skips_all(monkeypatch):
    """history_news_korean_summary_enabled=False면 영문 제목도 건드리지 않는다."""
    from app.infrastructure.config import settings as settings_module

    original = settings_module.get_settings
    mutated = original()
    monkeypatch.setattr(
        mutated, "history_news_korean_summary_enabled", False, raising=False
    )
    monkeypatch.setattr(settings_module, "get_settings", lambda: mutated)

    events = [_make_news("Apple's stock surges on strong earnings beat")]
    mock = AsyncMock()
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase.batch_titles",
        new=mock,
    ):
        await _enrich_news_details(events)
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_news_non_news_categories_untouched():
    """NEWS 외 카테고리는 대상에서 제외."""
    price = TimelineEvent(
        title="Some English Title That Is Long Enough To Trigger The Filter Logic",
        date=date(2026, 4, 21),
        category="PRICE",
        type="SURGE",
        detail="Some English detail",
        source=None,
    )
    mock = AsyncMock()
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase.batch_titles",
        new=mock,
    ):
        await _enrich_news_details([price])
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_news_batch_called_with_all_targets():
    """다건 NEWS 타겟이 단일 batch_titles 호출로 묶여 전달되는지 확인 (§13.4 B 핵심)."""
    events = [
        _make_news(f"English headline number {i} that triggers the filter logic")
        for i in range(5)
    ]
    mock = AsyncMock(return_value=[f"한국어 요약 {i}" for i in range(5)])
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase.batch_titles",
        new=mock,
    ):
        await _enrich_news_details(events)

    # batch_titles 가 1회만 호출되어야 함 — 단건 ainvoke × 5 회귀 방지
    assert mock.call_count == 1
    call_kwargs = mock.call_args.kwargs
    assert len(call_kwargs["items"]) == 5
    for i, e in enumerate(events):
        assert e.title == f"한국어 요약 {i}"
        assert e.detail == f"한국어 요약 {i}"
