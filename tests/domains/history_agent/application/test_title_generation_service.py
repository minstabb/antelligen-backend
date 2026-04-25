"""T2-4 batch_titles 에러 분류·재시도 및 T1-1 MACRO fallback 병합 테스트."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.history_agent.application.service.title_generation_service import (
    FALLBACK_TITLE,
    _classify_error,
    _is_rate_limit_error,
    batch_titles,
    default_fallback,
)


# ─── T1-1: FALLBACK_TITLE이 MACRO를 _SERIES_CONFIG에서 파생했는지 ──────────

def test_fallback_title_contains_macro_from_series_config():
    assert FALLBACK_TITLE["INTEREST_RATE"] == "기준금리 결정"
    assert FALLBACK_TITLE["CPI"] == "CPI 발표"
    assert FALLBACK_TITLE["UNEMPLOYMENT"] == "실업률 발표"


def test_fallback_title_contains_non_macro():
    assert FALLBACK_TITLE["SURGE"] == "급등"
    assert FALLBACK_TITLE["EARNINGS"] == "실적 발표"


def test_default_fallback_uses_label_when_type_unknown():
    item = MagicMock()
    item.type = "NEW_UNKNOWN_TYPE"
    item.label = "신규 지표"
    assert default_fallback(item) == "신규 지표"


# ─── T2-4: 에러 분류 ────────────────────────────────────────────────────

def test_classify_error_timeout():
    assert _classify_error(asyncio.TimeoutError()) == "timeout"


def test_classify_error_json():
    assert _classify_error(json.JSONDecodeError("x", "", 0)) == "json"


def test_classify_error_rate_limit():
    class RateLimitError(Exception):
        pass

    assert _is_rate_limit_error(RateLimitError()) is True
    assert _classify_error(RateLimitError()) == "rate_limit"


def test_classify_error_other():
    assert _classify_error(ValueError("boom")) == "other"


# ─── T2-4: batch_titles 재시도 동작 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_titles_retries_on_json_error():
    """JSON 파싱 실패 → 1회 재시도. 재시도가 성공하면 해당 타이틀을 반환."""
    call_count = {"n": 0}

    class _Resp:
        def __init__(self, content):
            self.content = content

    async def fake_ainvoke(messages):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _Resp("not-json")
        return _Resp('["첫번째","두번째"]')

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

    items = [MagicMock(type="SURGE"), MagicMock(type="PLUNGE")]
    with patch(
        "app.domains.history_agent.application.service.title_generation_service.get_workflow_llm",
        return_value=fake_llm,
    ):
        titles = await batch_titles(
            items, "system", lambda e: e.type, lambda e: "FALLBACK",
        )

    assert titles == ["첫번째", "두번째"]
    assert call_count["n"] == 2  # 첫 실패 + 재시도 성공


@pytest.mark.asyncio
async def test_batch_titles_returns_fallback_on_unrecoverable_error():
    class _Resp:
        def __init__(self, content):
            self.content = content

    async def always_fail(messages):
        raise ValueError("unrecoverable")

    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=always_fail)

    items = [MagicMock(type="SURGE")]
    with patch(
        "app.domains.history_agent.application.service.title_generation_service.get_workflow_llm",
        return_value=fake_llm,
    ):
        titles = await batch_titles(
            items, "system", lambda e: e.type, lambda e: "FALLBACK",
        )

    assert titles == ["FALLBACK"]
