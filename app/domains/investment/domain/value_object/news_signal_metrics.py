"""
뉴스 기사 기반 이벤트·키워드 투자 심리 지표 값 객체.

Domain Layer — 외부 의존성 없는 순수 Python TypedDict.
"""

from typing import TypedDict


class NewsEvent(TypedDict):
    event: str
    impact: str  # "high" | "medium" | "low"


class NewsSignalMetrics(TypedDict):
    """뉴스 기반 이벤트·키워드 투자 심리 지표."""

    positive_events: list[NewsEvent]
    negative_events: list[NewsEvent]
    keywords: list[str]
