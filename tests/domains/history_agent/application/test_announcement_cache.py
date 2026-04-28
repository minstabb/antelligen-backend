"""ANNOUNCEMENT 한국어 요약 Redis 캐시 동작 검증 (NEWS/MACRO 패턴 복제)."""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _enrich_announcement_details,
    _announcement_summary_cache_key,
)


_LONG_ENGLISH_DETAIL = (
    "Apple Inc. announced today that it has entered into an agreement with a major "
    "supplier to expand chip production capacity. The deal, valued at approximately "
    "$3.5 billion, is expected to support the company's upcoming generation of AI "
    "accelerators. Closing is anticipated in the third fiscal quarter."
)
_LONG_ENGLISH_DETAIL_2 = (
    "Microsoft Corporation reported that its board of directors approved a new $60 "
    "billion share repurchase program. The board also declared a quarterly dividend "
    "of $0.83 per share, payable to shareholders of record at the end of the quarter. "
    "The buyback has no fixed expiration date and may be paused or terminated."
)


def _make_announcement(detail: str) -> TimelineEvent:
    return TimelineEvent(
        title="공시",
        date=date(2026, 4, 21),
        category="ANNOUNCEMENT",
        type="ANNOUNCEMENT",
        detail=detail,
        source="sec",
    )


def test_cache_key_stable_for_same_detail():
    e1 = _make_announcement(_LONG_ENGLISH_DETAIL)
    e2 = _make_announcement(_LONG_ENGLISH_DETAIL)
    assert _announcement_summary_cache_key(e1.detail) == _announcement_summary_cache_key(e2.detail)


def test_cache_key_differs_for_different_detail():
    assert _announcement_summary_cache_key(_LONG_ENGLISH_DETAIL) != _announcement_summary_cache_key(
        _LONG_ENGLISH_DETAIL_2
    )


def test_cache_key_format_v2_full_sha256():
    # v2 — 전체 64-char SHA-256 사용 (collision 영향 0). 16-char 버전 v1 회귀 방어.
    key = _announcement_summary_cache_key(_LONG_ENGLISH_DETAIL)
    assert key.startswith("announcement_summary:v2:")
    hash_part = key.split(":", 2)[2]
    assert len(hash_part) == 64
    assert all(c in "0123456789abcdef" for c in hash_part)


@pytest.mark.asyncio
async def test_full_cache_hit_skips_llm():
    """전체 캐시 적중 시 _summarize_to_korean (LLM) 미호출."""
    events = [
        _make_announcement(_LONG_ENGLISH_DETAIL),
        _make_announcement(_LONG_ENGLISH_DETAIL_2),
    ]
    redis_mock = AsyncMock()
    redis_mock.mget = AsyncMock(
        return_value=[b"\xec\x95\xa0\xed\x94\x8c \xec\x9a\x94\xec\x95\xbd",  # "애플 요약"
                      b"\xeb\xa7\x88\xec\x9d\xb4\xed\x81\xac\xeb\xa1\x9c \xec\x9a\x94\xec\x95\xbd"],  # "마이크로 요약"
    )
    summarize_mock = AsyncMock()
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._summarize_to_korean",
        new=summarize_mock,
    ):
        await _enrich_announcement_details(events, redis=redis_mock)

    summarize_mock.assert_not_called()
    assert events[0].detail == "애플 요약"
    assert events[1].detail == "마이크로 요약"


@pytest.mark.asyncio
async def test_partial_cache_only_misses_to_llm():
    """일부 적중 시 miss 만 LLM. miss 결과 setex 저장."""
    events = [
        _make_announcement(_LONG_ENGLISH_DETAIL),       # cache hit
        _make_announcement(_LONG_ENGLISH_DETAIL_2),     # cache miss
    ]
    redis_mock = AsyncMock()
    redis_mock.mget = AsyncMock(return_value=[b"\xec\xba\x90\xec\x8b\x9c", None])  # "캐시", None

    pipe_mock = AsyncMock()
    pipe_mock.__aenter__ = AsyncMock(return_value=pipe_mock)
    pipe_mock.__aexit__ = AsyncMock(return_value=False)
    pipe_mock.execute = AsyncMock()
    pipe_mock.setex = lambda *a, **kw: None
    redis_mock.pipeline = lambda transaction=False: pipe_mock

    summarize_mock = AsyncMock(return_value="마이크로소프트 60B 자사주 매입")
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._summarize_to_korean",
        new=summarize_mock,
    ):
        await _enrich_announcement_details(events, redis=redis_mock)

    assert summarize_mock.call_count == 1
    assert events[0].detail == "캐시"
    assert events[1].detail == "마이크로소프트 60B 자사주 매입"
    pipe_mock.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_redis_falls_back_to_llm():
    """redis=None 이면 캐시 통과 후 _summarize_to_korean 직접 호출."""
    events = [_make_announcement(_LONG_ENGLISH_DETAIL)]
    summarize_mock = AsyncMock(return_value="애플 칩 공급 계약 35B")
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._summarize_to_korean",
        new=summarize_mock,
    ):
        await _enrich_announcement_details(events, redis=None)

    summarize_mock.assert_awaited_once()
    assert events[0].detail == "애플 칩 공급 계약 35B"


@pytest.mark.asyncio
async def test_korean_detail_skipped():
    """이미 한국어 detail 은 LLM·캐시 모두 통과."""
    events = [_make_announcement("삼성전자가 신형 HBM 양산을 시작했다고 공시했다.")]
    redis_mock = AsyncMock()
    summarize_mock = AsyncMock()
    with patch(
        "app.domains.history_agent.application.usecase.history_agent_usecase._summarize_to_korean",
        new=summarize_mock,
    ):
        await _enrich_announcement_details(events, redis=redis_mock)

    summarize_mock.assert_not_called()
    redis_mock.mget.assert_not_called()
