"""§13.4 B follow-up: enrich_macro_titles Redis 캐시 동작 검증."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.title_generation_service import (
    enrich_macro_titles,
    _macro_title_cache_key,
)


def _make_macro(type_: str, detail: str) -> TimelineEvent:
    """type 의 FALLBACK_TITLE 로 title 설정 — is_fallback_title=True 라 enrich 대상."""
    from app.domains.history_agent.application.service.title_generation_service import FALLBACK_TITLE
    title = FALLBACK_TITLE.get(type_, type_)
    return TimelineEvent(
        title=title,
        date=date(2025, 4, 1),
        category="MACRO",
        type=type_,
        detail=detail,
        source="FRED",
    )


def test_cache_key_stable_for_same_event():
    e1 = _make_macro("CPI", "CPI 4.0%")
    e2 = _make_macro("CPI", "CPI 4.0%")
    assert _macro_title_cache_key(e1) == _macro_title_cache_key(e2)


def test_cache_key_differs_for_different_detail():
    e1 = _make_macro("CPI", "CPI 4.0%")
    e2 = _make_macro("CPI", "CPI 4.5%")
    assert _macro_title_cache_key(e1) != _macro_title_cache_key(e2)


@pytest.mark.asyncio
async def test_full_cache_hit_skips_batch_titles():
    """전체 캐시 적중 시 LLM (batch_titles) 미호출."""
    events = [
        _make_macro("CPI", "CPI 4.0%"),
        _make_macro("FED", "기준금리 0.5% 인상"),
    ]
    redis_mock = AsyncMock()
    redis_mock.mget = AsyncMock(
        return_value=[b"\xec\xa0\x9c\xeb\xaa\xa9 1", b"\xec\xa0\x9c\xeb\xaa\xa9 2"],  # "제목 1", "제목 2" UTF-8
    )
    batch_mock = AsyncMock()
    with patch(
        "app.domains.history_agent.application.service.title_generation_service.batch_titles",
        new=batch_mock,
    ):
        await enrich_macro_titles(events, redis=redis_mock)

    batch_mock.assert_not_called()
    assert events[0].title == "제목 1"
    assert events[1].title == "제목 2"


@pytest.mark.asyncio
async def test_partial_cache_only_misses_to_llm():
    """일부 적중 시 miss 만 LLM. miss 결과 setex 저장."""
    events = [
        _make_macro("CPI", "CPI 4.0%"),  # cache hit
        _make_macro("FED", "기준금리 0.5% 인상"),  # cache miss
    ]
    redis_mock = AsyncMock()
    redis_mock.mget = AsyncMock(return_value=[b"\xec\xba\x90\xec\x8b\x9c", None])  # "캐시", None

    pipe_mock = AsyncMock()
    pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
    pipe_mock.__aexit__ = AsyncMock(return_value=False)
    pipe_mock.execute = AsyncMock()
    pipe_mock.setex = lambda *a, **kw: None
    redis_mock.pipeline = lambda transaction=False: pipe_mock

    batch_mock = AsyncMock(return_value=["기준금리 인상"])
    with patch(
        "app.domains.history_agent.application.service.title_generation_service.batch_titles",
        new=batch_mock,
    ):
        await enrich_macro_titles(events, redis=redis_mock)

    assert batch_mock.call_count == 1
    assert len(batch_mock.call_args.args[0]) == 1
    assert events[0].title == "캐시"
    assert events[1].title == "기준금리 인상"
    pipe_mock.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_redis_falls_back_to_batch_titles():
    """redis=None 이면 캐시 통과 후 batch_titles."""
    events = [_make_macro("CPI", "CPI 4.0%")]
    batch_mock = AsyncMock(return_value=["CPI 발표"])
    with patch(
        "app.domains.history_agent.application.service.title_generation_service.batch_titles",
        new=batch_mock,
    ):
        await enrich_macro_titles(events, redis=None)

    batch_mock.assert_called_once()
    assert events[0].title == "CPI 발표"


@pytest.mark.asyncio
async def test_fallback_title_not_cached():
    """LLM 실패로 fallback 그대로 남으면 setex 미저장 — 다음 호출 재시도 보존."""
    events = [_make_macro("CPI", "CPI 4.0%")]
    redis_mock = AsyncMock()
    redis_mock.mget = AsyncMock(return_value=[None])

    pipe_mock = AsyncMock()
    pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
    pipe_mock.__aexit__ = AsyncMock(return_value=False)
    pipe_mock.execute = AsyncMock()
    pipe_mock.setex = lambda *a, **kw: None
    redis_mock.pipeline = lambda transaction=False: pipe_mock

    # batch_titles 가 fallback 그대로 반환 (실패 케이스: type=CPI 의 FALLBACK_TITLE = "CPI 발표")
    batch_mock = AsyncMock(return_value=["CPI 발표"])
    with patch(
        "app.domains.history_agent.application.service.title_generation_service.batch_titles",
        new=batch_mock,
    ):
        await enrich_macro_titles(events, redis=redis_mock)

    # is_fallback_title 가 True 라 setex 호출되지 않음 — execute 가 await 안 됨
    pipe_mock.execute.assert_not_awaited()
