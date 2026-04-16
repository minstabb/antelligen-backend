"""
투자 판단 분석기 (Deterministic Rule Engine + LLM Rationale).

direction / confidence / verdict 는 입력 신호에 대해 항상 동일한 결과를 반환하는
deterministic 규칙으로 계산한다. LLM은 reasons / risk_factors 설명 생성에만 사용한다.

계산 흐름:
    1. news_score  = Σ(pos_events.impact_weight) - Σ(neg_events.impact_weight)
    2. direction   = bullish | neutral | bearish  (threshold 기반)
    3. confidence  = sigmoid(w1×|news_score| + w2×|sentiment_score|)
    4. verdict     = buy | hold | sell  (direction + confidence 기반)
    5. rationale   = LLM 호출 → reasons, risk_factors  (실패 시 이벤트 텍스트로 fallback)
"""

import json
import math
from typing import Any

from langchain_openai import ChatOpenAI

from app.domains.investment.domain.value_object.investment_decision import (
    InvestmentDecision,
    conservative_fallback,
)
from app.domains.investment.domain.value_object.youtube_sentiment_metrics import (
    NewsSignalMetrics,
    YoutubeSentimentMetrics,
)

# ── 파라미터 상수 ──────────────────────────────────────────────────────────────

# impact 문자열 → 가중치
_IMPACT_WEIGHTS: dict[str, float] = {"high": 3.0, "medium": 2.0, "low": 1.0}

# direction 결정 임계값 (news_score 기준)
_DIRECTION_THRESHOLD: float = 1.0

# confidence = sigmoid(w1×|news_score| + w2×|sentiment_score|)
_W1_NEWS: float = 0.3        # 뉴스 점수 기여 계수
_W2_SENTIMENT: float = 1.0   # YouTube 감성 기여 계수

# verdict 결정 confidence 임계값
_VERDICT_CONFIDENCE_THRESHOLD: float = 0.6


# ── 순수 함수 헬퍼 ─────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _impact_weight(impact: str) -> float:
    return _IMPACT_WEIGHTS.get(str(impact).lower(), 1.0)


def _compute_news_score(news_signal: NewsSignalMetrics) -> tuple[float, float, float]:
    """
    pos_score, neg_score, news_score 를 반환한다.
    각 이벤트의 impact 가중치를 합산한다.
    """
    pos_score = sum(
        _impact_weight(e.get("impact", "low"))
        for e in news_signal.get("positive_events", [])
    )
    neg_score = sum(
        _impact_weight(e.get("impact", "low"))
        for e in news_signal.get("negative_events", [])
    )
    return pos_score, neg_score, pos_score - neg_score


def _compute_direction(news_score: float) -> str:
    if news_score > _DIRECTION_THRESHOLD:
        return "bullish"
    elif news_score < -_DIRECTION_THRESHOLD:
        return "bearish"
    return "neutral"


def _compute_confidence(news_score: float, sentiment_score: float) -> float:
    raw = _W1_NEWS * abs(news_score) + _W2_SENTIMENT * abs(sentiment_score)
    return round(_sigmoid(raw), 4)


def _compute_verdict(direction: str, confidence: float) -> str:
    if direction == "bullish" and confidence > _VERDICT_CONFIDENCE_THRESHOLD:
        return "buy"
    if direction == "bearish" and confidence > _VERDICT_CONFIDENCE_THRESHOLD:
        return "sell"
    return "hold"


# ── 분석기 클래스 ──────────────────────────────────────────────────────────────

class InvestmentDecisionAnalyzer:
    """
    YoutubeSentimentMetrics + NewsSignalMetrics → InvestmentDecision.

    direction / confidence / verdict 는 deterministic rule로 결정되며,
    동일 입력에 대해 항상 동일한 결과를 반환한다.
    """

    def __init__(self, llm: ChatOpenAI) -> None:
        self._llm = llm

    async def analyze(
        self,
        youtube_sentiment: YoutubeSentimentMetrics,
        news_signal: NewsSignalMetrics,
        company: str,
        intent: str,
    ) -> InvestmentDecision:
        """
        투자 판단을 수행하고 InvestmentDecision을 반환한다.

        신호 부족(이벤트 0건 + 댓글 0건)이면 conservative_fallback()을 즉시 반환한다.
        LLM rationale 생성 실패 시 이벤트 텍스트로 대체하여 결과는 항상 반환된다.
        """
        print(f"\n[DecisionAnalyzer] 투자 판단 시작 | company={company!r} | intent={intent!r}")

        # ── 신호 부족 감지 ──────────────────────────────────────────────────
        has_news_events = bool(
            news_signal.get("positive_events") or news_signal.get("negative_events")
        )
        has_comments = youtube_sentiment.get("volume", 0) > 0

        if not has_news_events and not has_comments:
            print(f"[DecisionAnalyzer] 신호 없음 (이벤트 0건 + 댓글 0건) → 보수적 fallback 반환")
            return conservative_fallback()

        # ── Step 1: news_score 계산 ────────────────────────────────────────
        pos_score, neg_score, news_score = _compute_news_score(news_signal)
        sentiment_score = youtube_sentiment.get("sentiment_score", 0.0)

        print(f"[DecisionAnalyzer] ── Step 1: Score 계산")
        print(
            f"  positive_events: {len(news_signal.get('positive_events', []))}건 "
            f"→ weighted_sum = {pos_score:.1f}"
        )
        print(
            f"  negative_events: {len(news_signal.get('negative_events', []))}건 "
            f"→ weighted_sum = {neg_score:.1f}"
        )
        print(f"  news_score      = {pos_score:.1f} - {neg_score:.1f} = {news_score:+.1f}")
        print(f"  sentiment_score = {sentiment_score:+.4f}  (YouTube, 절대값 사용)")

        # ── Step 2: direction 결정 ─────────────────────────────────────────
        direction = _compute_direction(news_score)
        print(
            f"[DecisionAnalyzer] ── Step 2: Direction = {direction.upper()!r}  "
            f"(|news_score|={abs(news_score):.1f}, threshold=±{_DIRECTION_THRESHOLD})"
        )

        # ── Step 3: confidence 계산 ────────────────────────────────────────
        confidence = _compute_confidence(news_score, sentiment_score)
        raw_input = _W1_NEWS * abs(news_score) + _W2_SENTIMENT * abs(sentiment_score)
        print(
            f"[DecisionAnalyzer] ── Step 3: Confidence "
            f"= sigmoid({_W1_NEWS}×{abs(news_score):.2f} + {_W2_SENTIMENT}×{abs(sentiment_score):.4f})"
            f" = sigmoid({raw_input:.4f}) = {confidence:.4f}"
        )

        # ── Step 4: verdict 결정 ───────────────────────────────────────────
        verdict = _compute_verdict(direction, confidence)
        print(
            f"[DecisionAnalyzer] ── Step 4: Verdict = {verdict.upper()!r}  "
            f"(direction={direction}, confidence={confidence:.4f} "
            f"{'>' if confidence > _VERDICT_CONFIDENCE_THRESHOLD else '<='} {_VERDICT_CONFIDENCE_THRESHOLD})"
        )

        # ── Step 5: LLM rationale 생성 ────────────────────────────────────
        print(f"[DecisionAnalyzer] ── Step 5: LLM rationale 생성 중...")
        reasons, risk_factors = await self._generate_rationale(
            company=company,
            intent=intent,
            direction=direction,
            confidence=confidence,
            verdict=verdict,
            news_signal=news_signal,
            youtube_sentiment=youtube_sentiment,
        )

        decision: InvestmentDecision = {
            "direction": direction,
            "confidence": confidence,
            "verdict": verdict,
            "reasons": reasons,
            "risk_factors": risk_factors,
        }

        # ── 결과 출력 ──────────────────────────────────────────────────────
        verdict_label = {"buy": "매수(BUY)", "sell": "매도(SELL)", "hold": "보유(HOLD)"}.get(
            verdict, verdict
        )
        print(f"\n[DecisionAnalyzer] =========================================")
        print(f"  종목      : {company}")
        print(f"  방향성    : {direction.upper()}")
        print(f"  신뢰도    : {confidence:.1%}")
        print(f"  최종 의견 : {verdict_label}")
        print(f"  긍정 근거 ({len(reasons['positive'])}건):")
        for r in reasons["positive"]:
            print(f"    [+] {r}")
        print(f"  부정 근거 ({len(reasons['negative'])}건):")
        for r in reasons["negative"]:
            print(f"    [-] {r}")
        print(f"  리스크 요인 ({len(risk_factors)}건):")
        for r in risk_factors:
            print(f"    [!] {r}")
        print(f"[DecisionAnalyzer] =========================================\n")

        return decision

    async def _generate_rationale(
        self,
        company: str,
        intent: str,
        direction: str,
        confidence: float,
        verdict: str,
        news_signal: NewsSignalMetrics,
        youtube_sentiment: YoutubeSentimentMetrics,
    ) -> tuple[dict[str, list[str]], list[str]]:
        """
        LLM으로 reasons(positive/negative)와 risk_factors를 생성한다.

        실패 시 뉴스 이벤트 텍스트로 fallback하여 항상 결과를 반환한다.
        """
        pos_events_text = "\n".join(
            f"  [{e['impact'].upper()}] {e['event']}"
            for e in news_signal.get("positive_events", [])
        ) or "  없음"
        neg_events_text = "\n".join(
            f"  [{e['impact'].upper()}] {e['event']}"
            for e in news_signal.get("negative_events", [])
        ) or "  없음"

        dist = youtube_sentiment.get("sentiment_distribution", {})
        bullish_kw = ", ".join(youtube_sentiment.get("bullish_keywords", [])[:5]) or "없음"
        bearish_kw = ", ".join(youtube_sentiment.get("bearish_keywords", [])[:5]) or "없음"

        system_prompt = (
            "당신은 투자 판단 설명 전문가입니다.\n"
            "주어진 분석 결과를 바탕으로 투자 판단 근거와 리스크를 한국어로 생성하세요.\n"
            "반드시 아래 JSON 형식으로만 응답하세요 (마크다운·코드블록 금지):\n"
            "{\n"
            '  "positive_reasons": ["긍정 판단 근거 1문장", ...],\n'
            '  "negative_reasons": ["부정·주의 판단 근거 1문장", ...],\n'
            '  "risk_factors":     ["리스크 요인 1문장", ...]\n'
            "}"
        )

        user_prompt = (
            f"종목: {company}\n"
            f"사용자 의도: {intent}\n"
            f"판단 방향: {direction.upper()} | 신뢰도: {confidence:.1%} | 의견: {verdict.upper()}\n\n"
            f"[뉴스 긍정 이벤트]\n{pos_events_text}\n\n"
            f"[뉴스 부정 이벤트]\n{neg_events_text}\n\n"
            f"[YouTube 투자 심리]\n"
            f"  감성 분포: 긍정={dist.get('positive', 0):.0%} | "
            f"중립={dist.get('neutral', 0):.0%} | "
            f"부정={dist.get('negative', 0):.0%}\n"
            f"  강세 키워드: {bullish_kw}\n"
            f"  약세 키워드: {bearish_kw}\n\n"
            "위 데이터를 바탕으로 투자 판단 근거와 리스크 요인을 JSON으로 작성하세요."
        )

        try:
            response = await self._llm.ainvoke([
                ("system", system_prompt),
                ("human", user_prompt),
            ])
            raw = response.content.strip()
            print(f"[DecisionAnalyzer] rationale LLM 응답 수신 | 길이={len(raw)}자")
            data = json.loads(raw)

            reasons = {
                "positive": [str(r) for r in data.get("positive_reasons", [])],
                "negative": [str(r) for r in data.get("negative_reasons", [])],
            }
            risk_factors = [str(r) for r in data.get("risk_factors", [])]
            return reasons, risk_factors

        except Exception as exc:
            print(f"[DecisionAnalyzer] rationale LLM 실패: {exc!r} — 이벤트 텍스트로 fallback")
            reasons = {
                "positive": [e["event"] for e in news_signal.get("positive_events", [])],
                "negative": [e["event"] for e in news_signal.get("negative_events", [])],
            }
            risk_factors = [
                e["event"]
                for e in news_signal.get("negative_events", [])
                if e.get("impact") in ("high", "medium")
            ]
            return reasons, risk_factors
