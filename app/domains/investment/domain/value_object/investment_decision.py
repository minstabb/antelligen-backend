"""
투자 판단 결과 값 객체.

Domain Layer — 외부 의존성 없는 순수 Python TypedDict.
"""

from typing import TypedDict


class DecisionReasons(TypedDict):
    positive: list[str]
    negative: list[str]


class InvestmentDecision(TypedDict):
    """종목에 대한 구조화된 투자 판단 결과."""

    direction: str          # "bullish" | "bearish" | "neutral"
    confidence: float       # 0.0 ~ 1.0
    verdict: str            # "buy" | "hold" | "sell"
    reasons: DecisionReasons
    risk_factors: list[str]
    rationale: str          # LLM 생성 근거 요약 (판단 자체는 rule 기반)

    # 산출 과정 중간값 — 추적·디버깅용
    news_score: float       # 뉴스 impact 가중합 (양수=긍정, 음수=부정)
    sentiment_score: float  # 유튜브 감성 점수 (-1 ~ +1)
