"""
투자 심리 지표 값 객체.

YouTube 댓글 및 뉴스 기사로부터 산출되는 투자 심리 지표의 스키마를 정의한다.
Domain Layer에 위치하므로 순수 Python TypedDict만 사용한다.
"""

from typing import TypedDict


# ──────────────────────────────────────────────
# YouTube 댓글 감성 지표
# ──────────────────────────────────────────────

class SentimentDistribution(TypedDict):
    positive: float   # 0.0 ~ 1.0
    neutral: float    # 0.0 ~ 1.0
    negative: float   # 0.0 ~ 1.0


class YoutubeSentimentMetrics(TypedDict):
    sentiment_distribution: SentimentDistribution
    sentiment_score: float        # -1.0 ~ +1.0 (positive - negative)
    bullish_keywords: list[str]   # 긍정 댓글 대표 키워드 TOP N
    bearish_keywords: list[str]   # 부정 댓글 대표 키워드 TOP N
    topics: list[str]             # 주요 화제 TOP 5
    volume: int                   # 분석 기반 댓글 수


# ──────────────────────────────────────────────
# 뉴스 신호 지표
# ──────────────────────────────────────────────

class NewsEventItem(TypedDict):
    event: str    # 이벤트 설명 (1문장)
    impact: str   # "high" | "medium" | "low"


class NewsSignalMetrics(TypedDict):
    positive_events: list[NewsEventItem]
    negative_events: list[NewsEventItem]
    keywords: list[str]


# ──────────────────────────────────────────────
# 빈 결과 팩토리
# ──────────────────────────────────────────────

def empty_youtube_sentiment(volume: int = 0) -> YoutubeSentimentMetrics:
    """분석 불가 시 반환하는 빈 YouTube 감성 지표."""
    return {
        "sentiment_distribution": {"positive": 0.0, "neutral": 0.0, "negative": 0.0},
        "sentiment_score": 0.0,
        "bullish_keywords": [],
        "bearish_keywords": [],
        "topics": [],
        "volume": volume,
    }


def empty_news_signal() -> NewsSignalMetrics:
    """분석 불가 시 반환하는 빈 뉴스 신호 지표."""
    return {
        "positive_events": [],
        "negative_events": [],
        "keywords": [],
    }
