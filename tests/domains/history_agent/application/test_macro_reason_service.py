"""KR1 + KR2 5단계 + KR3 — Type B 사유 추정 서비스 검증."""
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.macro_reason_service import (
    enrich_type_b_reasons,
)
from app.domains.history_agent.application.service.title_generation_service import (
    MACRO_EVENT_TYPE,
    classify_macro_type,
)


def _make_macro(type_: str, day: int, detail: str = "", title: str = "", url: str = "") -> TimelineEvent:
    return TimelineEvent(
        title=title or type_,
        date=date(2024, 6, day),
        category="MACRO",
        type=type_,
        detail=detail,
        source="FRED",
        url=url or None,
    )


# ── KR1 분류 ─────────────────────────────────────────────────


def test_classify_macro_type_returns_type_a_for_release_events():
    e = _make_macro("CPI_RELEASE", 1, "CPI 4.0%")
    assert classify_macro_type(e) == "TYPE_A"


def test_classify_macro_type_returns_type_b_for_market_reaction_events():
    e = _make_macro("VIX_SPIKE", 1, "VIX 30+")
    assert classify_macro_type(e) == "TYPE_B"


def test_classify_macro_type_returns_none_for_unknown_type():
    e = _make_macro("UNKNOWN_FUTURE_TYPE", 1)
    assert classify_macro_type(e) is None


def test_classify_macro_type_returns_none_for_non_macro_event():
    e = TimelineEvent(
        title="x", date=date(2024, 6, 1), category="ANNOUNCEMENT", type="VIX_SPIKE", detail="",
    )
    assert classify_macro_type(e) is None


def test_macro_event_type_covers_all_known_market_reaction_types():
    """`_NON_MACRO_FALLBACK` 의 결과 이벤트 type 들이 모두 Type B 로 분류돼야 한다."""
    # 시장 반응 이벤트 5종 — KR2 fallback 대상.
    for t in ("VIX_SPIKE", "OIL_SPIKE", "GOLD_SPIKE", "US10Y_SPIKE", "FX_MOVE"):
        assert MACRO_EVENT_TYPE[t] == "TYPE_B", f"{t} 는 Type B 여야 함"


# ── KR2 1단계: 같은 날 Type A cross-ref ─────────────────────────


@pytest.mark.asyncio
async def test_same_day_cross_ref_fills_high_confidence_reason():
    type_a = _make_macro("FOMC_RATE_DECISION", 12, "기준금리 0.25%p 인상", title="연준 0.25%p 인상")
    type_b = _make_macro("VIX_SPIKE", 12, "VIX 30+")

    await enrich_type_b_reasons([type_a, type_b], redis=None)

    assert type_a.macro_type == "TYPE_A"
    assert type_b.macro_type == "TYPE_B"
    assert type_b.reason == "연준 0.25%p 인상 영향"
    assert type_b.reason_confidence == "HIGH"
    # url 없는 Type A → title fallback
    assert type_b.reason_evidence == "연준 0.25%p 인상"


@pytest.mark.asyncio
async def test_same_day_cross_ref_uses_url_when_available():
    """curated Type A 가 source_url 을 가지면 evidence 에 URL 흘림 → frontend 핑크 링크 활성화."""
    type_a = _make_macro(
        "FOMC_RATE_DECISION", 12,
        title="연준 0.25%p 인상",
        url="https://federalreserve.gov/newsevents/pressreleases/monetary20240612a.htm",
    )
    type_b = _make_macro("VIX_SPIKE", 12)

    await enrich_type_b_reasons([type_a, type_b], redis=None)

    assert type_b.reason_confidence == "HIGH"
    assert type_b.reason_evidence == (
        "https://federalreserve.gov/newsevents/pressreleases/monetary20240612a.htm"
    )


@pytest.mark.asyncio
async def test_no_same_day_match_without_redis_skips_llm_due_to_cutoff():
    """cross-ref 미매칭 + cutoff 이후 → reason None (cutoff 가드)."""
    type_b = _make_macro("VIX_SPIKE", 12)  # 2024-06-12, cutoff 2024-08-01 보다 이전이지만 LLM patch 로 검증

    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
    ) as get_llm_mock:
        llm_mock = MagicMock()
        llm_mock.ainvoke = AsyncMock(return_value=MagicMock(content='{"reason": "원인 미확인", "evidence": null}'))
        get_llm_mock.return_value = llm_mock

        await enrich_type_b_reasons([type_b], redis=None)

    # LLM 이 "원인 미확인" 또는 evidence 없음 응답이면 reason None.
    assert type_b.reason is None
    assert type_b.reason_confidence is None
    assert type_b.reason_evidence is None


# ── KR3-① cutoff 안전장치 ────────────────────────────────────


@pytest.mark.asyncio
async def test_event_after_cutoff_skips_llm_call():
    """이벤트 날짜 > cutoff 면 LLM 호출 자체가 일어나지 않아야 한다(hallucination 방지)."""
    type_b = TimelineEvent(
        title="VIX_SPIKE",
        date=date(2030, 1, 1),  # cutoff 2024-08-01 보다 한참 이후
        category="MACRO",
        type="VIX_SPIKE",
        detail="VIX 35+",
        source="FRED",
    )

    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(return_value=MagicMock(content='{"reason": "should not appear", "evidence": "fake"}'))

    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([type_b], redis=None)

    llm_mock.ainvoke.assert_not_called()
    assert type_b.reason is None
    assert type_b.reason_evidence is None


# ── KR3-③ evidence 강제 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_response_without_evidence_yields_none_reason():
    """LLM 이 evidence null 로 응답하면 reason 도 무효화."""
    type_b = _make_macro("VIX_SPIKE", 12)

    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(
        return_value=MagicMock(content='{"reason": "막연한 우려", "evidence": null}'),
    )
    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([type_b], redis=None)

    assert type_b.reason is None
    assert type_b.reason_evidence is None


@pytest.mark.asyncio
async def test_llm_response_with_evidence_records_low_confidence():
    """LLM 이 evidence 동반 응답이면 reason + evidence + LOW 신뢰도 기록."""
    type_b = _make_macro("VIX_SPIKE", 12)

    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"reason": "은행 위기 확산 우려", "evidence": "SVB 파산 보도"}',
        ),
    )
    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([type_b], redis=None)

    assert type_b.reason == "은행 위기 확산 우려"
    assert type_b.reason_confidence == "LOW"
    assert type_b.reason_evidence == "SVB 파산 보도"


# ── 캐시 동작 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_cache_hit_skips_llm_invocation():
    type_b = _make_macro("VIX_SPIKE", 12)
    redis_mock = AsyncMock()
    redis_mock.mget = AsyncMock(
        return_value=[
            '{"reason": "캐시 사유", "reason_confidence": "LOW", "reason_evidence": "cache evidence"}'.encode("utf-8"),
        ],
    )

    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock()
    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([type_b], redis=redis_mock)

    llm_mock.ainvoke.assert_not_called()
    assert type_b.reason == "캐시 사유"
    assert type_b.reason_confidence == "LOW"
    assert type_b.reason_evidence == "cache evidence"


# ── 빈 timeline / 비-MACRO ───────────────────────────────────


@pytest.mark.asyncio
async def test_empty_timeline_returns_without_calling_llm():
    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock()
    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([], redis=None)
    llm_mock.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_non_macro_events_unchanged():
    corp = TimelineEvent(
        title="자사주 매입",
        date=date(2024, 6, 12),
        category="CORPORATE",
        type="BUYBACK",
        detail="$10B 자사주",
    )
    await enrich_type_b_reasons([corp], redis=None)
    assert corp.macro_type is None
    assert corp.reason is None


# ── KR2-(2): ±7일 cross-ref (MEDIUM) ─────────────────────────


@pytest.mark.asyncio
async def test_window_cross_ref_picks_closest_type_a_within_seven_days():
    """같은 날 미매칭이면 가장 가까운 ±7일 Type A 로 채우고 MEDIUM 신뢰도."""
    near_a = _make_macro("FOMC_RATE_DECISION", 10, title="연준 금리 인상")
    far_a = _make_macro("CPI_RELEASE", 1, title="CPI 발표")
    type_b = _make_macro("VIX_SPIKE", 12)  # near_a 와 2일 차, far_a 와 11일 차

    await enrich_type_b_reasons([far_a, near_a, type_b], redis=None)

    assert type_b.reason == "연준 금리 인상 2일 후 영향"
    assert type_b.reason_confidence == "MEDIUM"
    # url 없는 Type A → title fallback
    assert type_b.reason_evidence == "연준 금리 인상"


@pytest.mark.asyncio
async def test_window_cross_ref_uses_url_when_available():
    """±7일 cross-ref 에서도 url 우선, fallback title."""
    near_a = _make_macro(
        "FOMC_RATE_DECISION", 10,
        title="연준 금리 인상",
        url="https://federalreserve.gov/example",
    )
    type_b = _make_macro("VIX_SPIKE", 12)

    await enrich_type_b_reasons([near_a, type_b], redis=None)

    assert type_b.reason_confidence == "MEDIUM"
    assert type_b.reason_evidence == "https://federalreserve.gov/example"


@pytest.mark.asyncio
async def test_window_cross_ref_skipped_when_outside_window():
    """±7일 윈도우 초과면 cross-ref 미매칭 → LLM 단계 진입(여기선 cutoff skip)."""
    far_a = _make_macro("CPI_RELEASE", 1, title="CPI 발표")
    type_b = TimelineEvent(
        title="VIX",
        date=date(2030, 6, 15),  # cutoff 이후, far_a 와 6년 차
        category="MACRO",
        type="VIX_SPIKE",
        detail="",
        source="FRED",
    )

    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock()
    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([far_a, type_b], redis=None)

    # 윈도우 초과 + cutoff 이후 → reason None, LLM 미호출.
    llm_mock.ainvoke.assert_not_called()
    assert type_b.reason is None
    assert type_b.reason_confidence is None


@pytest.mark.asyncio
async def test_same_day_takes_precedence_over_window():
    """같은 날 Type A 가 있으면 ±7일 후보보다 우선(HIGH 유지)."""
    same_day_a = _make_macro("FOMC_RATE_DECISION", 12, title="연준 금리 동결")
    window_a = _make_macro("CPI_RELEASE", 10, title="CPI 발표")
    type_b = _make_macro("VIX_SPIKE", 12)

    await enrich_type_b_reasons([window_a, same_day_a, type_b], redis=None)

    assert type_b.reason == "연준 금리 동결 영향"
    assert type_b.reason_confidence == "HIGH"
    assert type_b.reason_evidence == "연준 금리 동결"


# ── KR2-(3): 뉴스 검색 (MEDIUM) ───────────────────────────────


class _StubNewsPort:
    """MacroNewsSearchPort 의 in-memory stub."""
    def __init__(self, articles):
        self._articles = articles
        self.calls = []

    async def search(self, keyword, start_date, end_date):
        self.calls.append((keyword, start_date, end_date))
        return self._articles


@pytest.mark.asyncio
async def test_news_search_fills_reason_with_first_article_title():
    """cross-ref 미매칭이면 GDELT 뉴스 첫 article 의 title 을 reason 으로(MEDIUM)."""
    type_b = _make_macro("VIX_SPIKE", 12)
    news_port = _StubNewsPort([
        {"title": "Fed signals hawkish stance amid sticky inflation",
         "url": "https://example.com/fed-hawkish",
         "date": "20240612", "source": "gdelt"},
    ])

    await enrich_type_b_reasons([type_b], redis=None, news_search_port=news_port)

    assert type_b.reason == "Fed signals hawkish stance amid sticky inflation"
    assert type_b.reason_confidence == "MEDIUM"
    assert type_b.reason_evidence == "https://example.com/fed-hawkish"
    # ±2일 윈도우로 호출됐는지 확인.
    keyword, start, end = news_port.calls[0]
    assert keyword == "stock market volatility VIX surge"
    assert (end - start).days == 4


@pytest.mark.asyncio
async def test_news_search_empty_response_falls_through_to_llm():
    """뉴스 검색이 빈 결과면 LLM 단계로 넘어간다."""
    type_b = _make_macro("VIX_SPIKE", 12)
    news_port = _StubNewsPort([])

    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(
        return_value=MagicMock(content='{"reason": "원인 미확인", "evidence": null}'),
    )
    with patch(
        "app.domains.history_agent.application.service.macro_reason_service.get_workflow_llm",
        return_value=llm_mock,
    ):
        await enrich_type_b_reasons([type_b], redis=None, news_search_port=news_port)

    # 뉴스 미해결 → LLM 호출됨, LLM 미해결 → reason None.
    assert llm_mock.ainvoke.called
    assert type_b.reason is None


@pytest.mark.asyncio
async def test_news_search_skipped_when_keyword_missing():
    """type 별 키워드 매핑이 없으면 뉴스 검색 자체 skip."""
    type_b = TimelineEvent(
        title="x", date=date(2024, 6, 12), category="MACRO",
        type="UNKNOWN_REACTION_TYPE", detail="", source="FRED",
    )
    news_port = _StubNewsPort([{"title": "should not appear", "url": ""}])

    await enrich_type_b_reasons([type_b], redis=None, news_search_port=news_port)

    assert news_port.calls == []
    # MACRO 분류 미정의이므로 macro_type=None → Type B 분류 자체에서 제외 → reason 채워지지 않음.
    assert type_b.macro_type is None


@pytest.mark.asyncio
async def test_news_search_uses_url_as_evidence_with_title_fallback():
    """url 이 비어있으면 title 자체를 evidence 로 사용."""
    type_b = _make_macro("OIL_SPIKE", 12)
    news_port = _StubNewsPort([
        {"title": "OPEC+ surprise output cut", "url": "", "date": "20240612"},
    ])

    await enrich_type_b_reasons([type_b], redis=None, news_search_port=news_port)

    assert type_b.reason == "OPEC+ surprise output cut"
    assert type_b.reason_evidence == "OPEC+ surprise output cut"


@pytest.mark.asyncio
async def test_news_cache_hit_skips_external_call():
    """Redis 캐시에 뉴스 응답이 있으면 port.search 미호출."""
    type_b = _make_macro("VIX_SPIKE", 12)
    cached_articles = [
        {"title": "Cached headline", "url": "https://example.com/cache"},
    ]
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(
        return_value=json.dumps(cached_articles).encode("utf-8"),
    )
    redis_mock.mget = AsyncMock(return_value=[None])  # LLM 캐시는 miss

    news_port = _StubNewsPort([{"title": "should not appear", "url": ""}])

    await enrich_type_b_reasons([type_b], redis=redis_mock, news_search_port=news_port)

    assert news_port.calls == []
    assert type_b.reason == "Cached headline"
    assert type_b.reason_confidence == "MEDIUM"
