"""S2-7: ETF holdings 분해 시 (date, title) 중복 제거."""
from datetime import date

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _dedupe_etf_timeline,
)


def _evt(
    title: str,
    d: date,
    category: str = "CORPORATE",
    constituent_ticker: str | None = None,
) -> TimelineEvent:
    return TimelineEvent(
        title=title,
        date=d,
        category=category,
        type="EARNINGS",
        detail=f"detail-{title}",
        source="src",
        constituent_ticker=constituent_ticker,
    )


def test_holding_event_preserved_over_etf_self_event():
    """동일 (date, category, title) 에서 holding(constituent_ticker 명시) 이벤트 우선 보존."""
    same_date = date(2024, 7, 30)
    etf_self = _evt("AAPL Q3 실적 발표", same_date)  # ETF 자체 이벤트(no constituent)
    holding = _evt("AAPL Q3 실적 발표", same_date, constituent_ticker="AAPL")

    result = _dedupe_etf_timeline([etf_self, holding])

    assert len(result) == 1
    assert result[0].constituent_ticker == "AAPL"


def test_holding_first_then_etf_self_keeps_holding():
    """순서가 달라도 holding 이벤트 보존."""
    same_date = date(2024, 7, 30)
    holding = _evt("AAPL Q3 실적 발표", same_date, constituent_ticker="AAPL")
    etf_self = _evt("AAPL Q3 실적 발표", same_date)

    result = _dedupe_etf_timeline([holding, etf_self])

    assert len(result) == 1
    assert result[0].constituent_ticker == "AAPL"


def test_unique_events_unaffected():
    """다른 (date, category, title) 조합은 모두 보존."""
    events = [
        _evt("AAPL 실적 발표", date(2024, 7, 30), constituent_ticker="AAPL"),
        _evt("MSFT 실적 발표", date(2024, 7, 30), constituent_ticker="MSFT"),
        _evt("AAPL 실적 발표", date(2024, 10, 30), constituent_ticker="AAPL"),  # 다른 일자
    ]
    result = _dedupe_etf_timeline(events)
    assert len(result) == 3


def test_different_categories_not_deduped():
    """동일 (date, title) 이라도 category 가 다르면 별개 이벤트."""
    same_date = date(2024, 7, 30)
    events = [
        _evt("애플 8-K", same_date, category="ANNOUNCEMENT"),
        _evt("애플 8-K", same_date, category="NEWS"),
    ]
    result = _dedupe_etf_timeline(events)
    assert len(result) == 2
