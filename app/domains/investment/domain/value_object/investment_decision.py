"""
투자 판단 결과 값 객체.

direction / confidence / verdict 는 deterministic rule 기반으로 계산된다.
reasons / risk_factors 는 LLM이 생성하는 설명 텍스트다.

Domain Layer에 위치하므로 순수 Python TypedDict만 사용한다.
"""

from typing import TypedDict


class ReasonGroup(TypedDict):
    positive: list[str]   # 매수 근거
    negative: list[str]   # 매도·주의 근거


class InvestmentDecision(TypedDict):
    direction: str        # "bullish" | "bearish" | "neutral"
    confidence: float     # 0.0 ~ 1.0
    verdict: str          # "buy" | "hold" | "sell"
    reasons: ReasonGroup
    risk_factors: list[str]


def conservative_fallback() -> InvestmentDecision:
    """신호 부족·분석 실패 시 반환하는 보수적 기본값."""
    return {
        "direction": "neutral",
        "confidence": 0.2,
        "verdict": "hold",
        "reasons": {"positive": [], "negative": []},
        "risk_factors": ["입력 신호 부족으로 인해 판단을 보류합니다."],
    }
