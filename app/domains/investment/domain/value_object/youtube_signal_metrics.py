"""
유튜브 댓글 기반 투자 심리 지표 값 객체.

Domain Layer — 외부 의존성 없는 순수 Python TypedDict.
"""

from typing import TypedDict


class SentimentDistribution(TypedDict):
    positive: float  # 0.0 ~ 1.0
    neutral: float
    negative: float


class YoutubeSignalMetrics(TypedDict):
    """유튜브 댓글 감성·키워드 기반 투자 심리 지표."""

    sentiment_distribution: SentimentDistribution
    sentiment_score: float   # -1.0 (완전 부정) ~ +1.0 (완전 긍정)
    bullish_keywords: list[str]
    bearish_keywords: list[str]
    topics: list[str]
    volume: int              # 분석 기반 댓글 총 건수
