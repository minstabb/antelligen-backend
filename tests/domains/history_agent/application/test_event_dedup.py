"""T2-7 Step 2 공시 dedupe + 기본 유틸 검증."""

import datetime

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _announcement_source_rank,
    _dedupe_announcements,
    _jaccard_similarity,
)


def test_jaccard_similarity_identical():
    assert _jaccard_similarity("a b c", "a b c") == 1.0


def test_jaccard_similarity_disjoint():
    assert _jaccard_similarity("a b", "c d") == 0.0


def test_jaccard_similarity_partial_overlap():
    sim = _jaccard_similarity("apple reports q3", "apple q3 earnings")
    assert 0.3 < sim < 0.8


def test_jaccard_similarity_empty():
    assert _jaccard_similarity("", "anything") == 0.0


def test_announcement_source_rank_ordering():
    assert _announcement_source_rank("DART") < _announcement_source_rank("SEC")
    assert _announcement_source_rank("SEC") < _announcement_source_rank("YAHOO")
    assert _announcement_source_rank(None) > _announcement_source_rank("YAHOO")


def _make_announcement(
    date: datetime.date, detail: str, source: str, type_: str = "CONTRACT"
) -> TimelineEvent:
    return TimelineEvent(
        title="주요 공시",
        date=date,
        category="ANNOUNCEMENT",
        type=type_,
        detail=detail,
        source=source,
    )


def test_dedupe_keeps_single_announcement_unchanged():
    today = datetime.date(2025, 1, 1)
    events = [_make_announcement(today, "삼성전자 공급 계약 체결", "DART")]
    assert _dedupe_announcements(events) == events


def test_dedupe_collapses_similar_same_day_keeps_dart():
    today = datetime.date(2025, 1, 1)
    events = [
        _make_announcement(today, "삼성전자 공급 계약 체결 주요 내용", "SEC"),
        _make_announcement(today, "삼성전자 공급 계약 체결 주요 내용", "DART"),
        _make_announcement(today, "삼성전자 공급 계약 체결 주요 내용", "YAHOO"),
    ]
    result = _dedupe_announcements(events)
    announcements = [e for e in result if e.category == "ANNOUNCEMENT"]
    assert len(announcements) == 1
    assert announcements[0].source == "DART"


def test_dedupe_preserves_distinct_announcements_same_day():
    today = datetime.date(2025, 1, 1)
    events = [
        _make_announcement(today, "삼성전자 공급 계약 체결 주요 내용", "DART"),
        _make_announcement(today, "SK하이닉스 신규 투자 발표 핵심 요약", "DART"),
    ]
    result = _dedupe_announcements(events)
    assert len(result) == 2


def test_dedupe_does_not_touch_non_announcement_events():
    today = datetime.date(2025, 1, 1)
    price = TimelineEvent(
        title="갭 상승 (+3%)",
        date=today,
        category="PRICE",
        type="GAP_UP",
        detail="갭 상승",
        source=None,
    )
    events = [
        price,
        _make_announcement(today, "삼성전자 공급 계약 체결 주요 내용", "SEC"),
        _make_announcement(today, "삼성전자 공급 계약 체결 주요 내용", "DART"),
    ]
    result = _dedupe_announcements(events)
    assert any(e.category == "PRICE" for e in result)
    announcements = [e for e in result if e.category == "ANNOUNCEMENT"]
    assert len(announcements) == 1
    assert announcements[0].source == "DART"


def test_dedupe_handles_different_days_independently():
    d1 = datetime.date(2025, 1, 1)
    d2 = datetime.date(2025, 1, 2)
    events = [
        _make_announcement(d1, "삼성전자 공급 계약 체결 주요 내용", "SEC"),
        _make_announcement(d2, "삼성전자 공급 계약 체결 주요 내용", "DART"),
    ]
    result = _dedupe_announcements(events)
    # 다른 날짜는 유사해도 각각 유지
    assert len(result) == 2
