"""
투자 판단 결정 규칙 엔진 (Domain Service).

Domain Layer — 순수 Python, 외부 의존성 없음.

역할:
  - 뉴스 이벤트 impact 가중합 → news_score
  - 유튜브 감성 점수를 보조 신호로 결합 → confidence (sigmoid 정규화)
  - direction / verdict 결정 규칙 적용

모든 연산은 deterministic 하며 동일 입력에 대해 항상 동일 결과를 반환한다.
LLM은 이 모듈에 포함되지 않는다.

파라미터 기본값:
  IMPACT_WEIGHTS : high=3, medium=2, low=1
  NEWS_THRESHOLD : 1.5  (low 1개 초과 시 방향성 인정)
  W1             : 1.0  (뉴스 score 가중치)
  W2             : 0.5  (감성 score 가중치)
  VERDICT_CONFIDENCE_THRESHOLD : 0.6
"""

import math

# ── 상수 ──────────────────────────────────────────────────────────────────────

IMPACT_WEIGHTS: dict[str, float] = {
    "high":   3.0,
    "medium": 2.0,
    "low":    1.0,
}

# 뉴스 score가 이 값을 초과/미만일 때 bullish/bearish 판정
NEWS_THRESHOLD: float = 1.5

# confidence sigmoid 입력 가중치
W1: float = 1.0   # news_score 절대값 가중치
W2: float = 0.5   # sentiment_score 절대값 가중치

# verdict 결정 임계 confidence
VERDICT_CONFIDENCE_THRESHOLD: float = 0.6

# 보수적 fallback 시 반환하는 최대 confidence
FALLBACK_CONFIDENCE: float = 0.2


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    """표준 sigmoid 함수. 입력이 매우 크거나 작아도 오버플로 없이 처리한다."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _impact_weight(impact: str) -> float:
    return IMPACT_WEIGHTS.get(impact.lower(), 1.0)


# ── 공개 함수 ──────────────────────────────────────────────────────────────────

def compute_news_score(
    positive_events: list[dict],
    negative_events: list[dict],
) -> float:
    """
    뉴스 이벤트 impact 가중합으로 news_score를 계산한다.

    news_score = Σ(긍정 impact 가중치) - Σ(부정 impact 가중치)

    반환값이 양수이면 긍정 우세, 음수이면 부정 우세.
    """
    pos = sum(_impact_weight(e.get("impact", "low")) for e in positive_events)
    neg = sum(_impact_weight(e.get("impact", "low")) for e in negative_events)
    return round(pos - neg, 4)


def compute_direction(news_score: float, threshold: float = NEWS_THRESHOLD) -> str:
    """
    news_score와 threshold를 비교하여 방향성을 결정한다.

    direction은 뉴스 신호만으로 결정한다 (유튜브는 confidence 보정에만 사용).
    """
    if news_score > threshold:
        return "bullish"
    if news_score < -threshold:
        return "bearish"
    return "neutral"


def compute_confidence(news_score: float, sentiment_score: float) -> float:
    """
    뉴스 score와 유튜브 감성 점수를 sigmoid로 결합하여 confidence를 계산한다.

    confidence = sigmoid(W1 * |news_score| + W2 * |sentiment_score|)

    뉴스가 방향성과 강도를 제공하고, 유튜브 sentiment는 확신도를 보정한다.
    """
    raw = W1 * abs(news_score) + W2 * abs(sentiment_score)
    return round(_sigmoid(raw), 4)


def compute_verdict(direction: str, confidence: float) -> str:
    """
    direction과 confidence 기반으로 최종 verdict(buy / hold / sell)를 결정한다.

    bullish + confidence > 0.6  → buy
    bearish + confidence > 0.6  → sell
    그 외                        → hold
    """
    if direction == "bullish" and confidence > VERDICT_CONFIDENCE_THRESHOLD:
        return "buy"
    if direction == "bearish" and confidence > VERDICT_CONFIDENCE_THRESHOLD:
        return "sell"
    return "hold"


def is_signal_insufficient(
    positive_events: list[dict],
    negative_events: list[dict],
    volume: int,
) -> bool:
    """
    방향성 계산에 필요한 핵심 신호(뉴스 이벤트)가 없을 때 True를 반환한다.

    기준:
      - 긍정·부정 뉴스 이벤트가 모두 0건인 경우만 신호 부족으로 판단한다.
      - 유튜브 댓글(volume)은 confidence 보정용 보조 신호이므로
        댓글이 없어도 뉴스 이벤트가 있으면 정상 계산을 진행한다.
    """
    return len(positive_events) == 0 and len(negative_events) == 0
