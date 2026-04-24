"""
투자 판단 산출 어댑터 (Adapter Layer — Outbound / External).

흐름:
  1. 도메인 서비스(investment_decision_engine)로 news_score, direction,
     confidence, verdict 를 deterministic 하게 계산한다.
  2. LLM을 호출하여 reasons(긍정·부정 요인), risk_factors, rationale 텍스트를 생성한다.
     LLM 호출이 실패해도 rule 기반 결과는 유지되고, fallback 텍스트가 채워진다.
  3. 입력 신호가 모두 비어있으면 보수적 기본값(hold, confidence=0.2)을 반환한다.

direction / confidence / verdict 는 LLM에 의해 변경되지 않는다.
"""

import json
import traceback
from typing import Optional

from langchain_openai import ChatOpenAI

from app.domains.investment.application.port.investment_decision_port import InvestmentDecisionPort
from app.domains.investment.domain.service.investment_decision_engine import (
    FALLBACK_CONFIDENCE,
    compute_confidence,
    compute_direction,
    compute_news_score,
    compute_verdict,
    is_signal_insufficient,
)
from app.domains.investment.domain.value_object.investment_decision import (
    DecisionReasons,
    InvestmentDecision,
)
from app.domains.investment.domain.value_object.news_signal_metrics import NewsSignalMetrics
from app.domains.investment.domain.value_object.youtube_signal_metrics import YoutubeSignalMetrics

_VERDICT_KO = {"buy": "매수", "hold": "보유", "sell": "매도"}
_DIRECTION_KO = {"bullish": "상승", "bearish": "하락", "neutral": "중립"}


def _conservative_fallback(reason: str) -> InvestmentDecision:
    """신호 부족·오류 시 반환하는 보수적 기본 판단."""
    return InvestmentDecision(
        direction="neutral",
        confidence=FALLBACK_CONFIDENCE,
        verdict="hold",
        reasons=DecisionReasons(positive=[], negative=[]),
        risk_factors=["신호 데이터 부족으로 판단 유보"],
        rationale=f"[보수적 기본값] {reason}",
        news_score=0.0,
        sentiment_score=0.0,
    )


class InvestmentDecisionAnalyzer(InvestmentDecisionPort):
    """
    뉴스·유튜브 심리 지표로부터 구조화된 투자 판단을 산출하는 구현체.

    deterministic rule → LLM rationale 순서로 동작한다.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._llm = ChatOpenAI(api_key=api_key, model=model, temperature=0)

    # ── 공개 메서드 ───────────────────────────────────────────────────────────

    async def analyze(
        self,
        *,
        news_signal: Optional[NewsSignalMetrics],
        youtube_signal: Optional[YoutubeSignalMetrics],
        company: Optional[str],
        intent: str,
    ) -> InvestmentDecision:
        """
        두 신호를 결합하여 buy / hold / sell 판단을 반환한다.

        Returns:
            InvestmentDecision — 신호 부족 시 보수적 fallback.
        """
        company_label = company or "전체 시장"

        # ── 신호 값 추출 ──────────────────────────────────────────────────────
        pos_events = (news_signal or {}).get("positive_events", [])
        neg_events = (news_signal or {}).get("negative_events", [])
        news_kws   = (news_signal or {}).get("keywords", [])

        sentiment_score = (youtube_signal or {}).get("sentiment_score", 0.0)
        yt_volume       = (youtube_signal or {}).get("volume", 0)
        bull_kws        = (youtube_signal or {}).get("bullish_keywords", [])
        bear_kws        = (youtube_signal or {}).get("bearish_keywords", [])
        dist            = (youtube_signal or {}).get("sentiment_distribution", {})

        print(f"\n[DecisionAnalyzer] 판단 시작 | company={company_label!r} | intent={intent!r}")
        print(
            f"[DecisionAnalyzer] 입력 신호 요약 "
            f"| 긍정이벤트={len(pos_events)}건 | 부정이벤트={len(neg_events)}건 "
            f"| yt_volume={yt_volume} | sentiment={sentiment_score:+.3f}"
        )

        # ── 신호 부족 체크 → 보수적 fallback ─────────────────────────────────
        if is_signal_insufficient(pos_events, neg_events, yt_volume):
            print("[DecisionAnalyzer] 신호 부족 → 보수적 fallback 반환 (hold, confidence=0.2)")
            return _conservative_fallback("뉴스 이벤트와 유튜브 댓글 모두 수집되지 않았습니다.")

        # ── Step 1: Deterministic rule 계산 ──────────────────────────────────
        news_score  = compute_news_score(pos_events, neg_events)
        direction   = compute_direction(news_score)
        confidence  = compute_confidence(news_score, sentiment_score)
        verdict     = compute_verdict(direction, confidence)

        print(
            f"[DecisionAnalyzer] ── Rule 계산 결과 ──────────────────────\n"
            f"  news_score  = {news_score:+.4f}  "
            f"(pos={sum(3 if e['impact']=='high' else 2 if e['impact']=='medium' else 1 for e in pos_events):.0f}"
            f" - neg={sum(3 if e['impact']=='high' else 2 if e['impact']=='medium' else 1 for e in neg_events):.0f})\n"
            f"  direction   = {direction}  (threshold=±1.5)\n"
            f"  confidence  = {confidence:.4f}  "
            f"(sigmoid(W1={1.0}*|{news_score:.2f}| + W2={0.5}*|{sentiment_score:.3f}|))\n"
            f"  verdict     = {verdict}  "
            f"({'confidence > 0.6 충족' if confidence > 0.6 else 'confidence ≤ 0.6 → hold'})\n"
            f"  ─────────────────────────────────────────────────────"
        )

        # ── Step 2: LLM rationale 생성 ───────────────────────────────────────
        llm_result = await self._generate_rationale(
            company=company_label,
            intent=intent,
            direction=direction,
            confidence=confidence,
            verdict=verdict,
            news_score=news_score,
            sentiment_score=sentiment_score,
            pos_events=pos_events,
            neg_events=neg_events,
            news_kws=news_kws,
            bull_kws=bull_kws,
            bear_kws=bear_kws,
            dist=dist,
        )

        decision = InvestmentDecision(
            direction=direction,
            confidence=confidence,
            verdict=verdict,
            reasons=llm_result["reasons"],
            risk_factors=llm_result["risk_factors"],
            rationale=llm_result["rationale"],
            news_score=news_score,
            sentiment_score=sentiment_score,
        )

        # ── 최종 판단 pretty-print ─────────────────────────────────────────
        self._print_decision(decision, company_label)
        return decision

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    async def _generate_rationale(
        self,
        *,
        company: str,
        intent: str,
        direction: str,
        confidence: float,
        verdict: str,
        news_score: float,
        sentiment_score: float,
        pos_events: list,
        neg_events: list,
        news_kws: list,
        bull_kws: list,
        bear_kws: list,
        dist: dict,
    ) -> dict:
        """
        LLM을 호출하여 reasons / risk_factors / rationale 를 생성한다.

        판단 결과(direction/confidence/verdict)는 이미 확정되어 있으며,
        LLM은 그 결과에 대한 설명 텍스트만 생성한다.

        LLM 실패 시 뉴스 이벤트 텍스트로 rule-based fallback을 반환한다.
        """
        pos_event_lines = "\n".join(
            f"  - [{e.get('impact','?')}] {e.get('event','')}" for e in pos_events
        ) or "  - 없음"
        neg_event_lines = "\n".join(
            f"  - [{e.get('impact','?')}] {e.get('event','')}" for e in neg_events
        ) or "  - 없음"

        system_prompt = (
            "당신은 한국 주식 투자 분석 보조자입니다. "
            "이미 확정된 투자 판단에 대해 근거 텍스트만 작성하세요. "
            "반드시 JSON만 응답하고 마크다운·코드블록은 사용하지 마세요."
        )
        user_prompt = f"""아래 데이터를 바탕으로 [{company}] 투자 판단 근거를 작성하세요.

[이미 확정된 판단]
- direction  : {direction} ({_DIRECTION_KO.get(direction, direction)})
- confidence : {confidence:.3f}
- verdict    : {verdict} ({_VERDICT_KO.get(verdict, verdict)})
- news_score : {news_score:+.2f}
- sentiment  : {sentiment_score:+.3f}

[뉴스 긍정 이벤트]
{pos_event_lines}

[뉴스 부정 이벤트]
{neg_event_lines}

[뉴스 키워드] {', '.join(news_kws[:7]) or '없음'}
[유튜브 상승 키워드] {', '.join(bull_kws[:5]) or '없음'}
[유튜브 하락 키워드] {', '.join(bear_kws[:5]) or '없음'}
[유튜브 감성 분포] 긍정={dist.get('positive',0):.1%} | 중립={dist.get('neutral',0):.1%} | 부정={dist.get('negative',0):.1%}
[사용자 의도] {intent}

아래 JSON 형식으로만 응답하세요:
{{
  "reasons": {{
    "positive": ["긍정 근거 1", "긍정 근거 2", "긍정 근거 3"],
    "negative": ["부정 근거 1", "부정 근거 2"]
  }},
  "risk_factors": ["리스크 1", "리스크 2", "리스크 3"],
  "rationale": "전체 판단 근거 요약 (2~3문장)"
}}

작성 규칙:
- reasons.positive/negative 는 각각 최대 5개, 뉴스 이벤트와 유튜브 신호를 근거로 사용
- risk_factors 는 최대 4개
- rationale 은 verdict 와 confidence 수준이 나온 이유를 자연스럽게 설명"""

        try:
            response = await self._llm.ainvoke([
                ("system", system_prompt),
                ("human", user_prompt),
            ])
            raw = response.content.strip()
            print(f"[DecisionAnalyzer] LLM rationale 수신 | 길이={len(raw)}자")
            data = json.loads(raw)
            reasons_raw = data.get("reasons", {})
            return {
                "reasons": DecisionReasons(
                    positive=list(reasons_raw.get("positive", []))[:5],
                    negative=list(reasons_raw.get("negative", []))[:5],
                ),
                "risk_factors": list(data.get("risk_factors", []))[:4],
                "rationale": str(data.get("rationale", "")),
            }
        except Exception as e:
            print(f"[DecisionAnalyzer] LLM rationale 실패 → rule-based fallback: {e}")
            traceback.print_exc()
            # rule-based fallback: 이벤트 텍스트를 그대로 사용
            return {
                "reasons": DecisionReasons(
                    positive=[e.get("event", "") for e in pos_events[:3]],
                    negative=[e.get("event", "") for e in neg_events[:3]],
                ),
                "risk_factors": [e.get("event", "") for e in neg_events[:3]],
                "rationale": (
                    f"{company} 에 대한 뉴스 score={news_score:+.2f}, "
                    f"감성점수={sentiment_score:+.3f} 기반으로 {verdict} 판단."
                ),
            }

    @staticmethod
    def _print_decision(d: InvestmentDecision, company: str) -> None:
        """최종 InvestmentDecision 을 보기 좋게 콘솔에 출력한다."""
        verdict_ko = _VERDICT_KO.get(d["verdict"], d["verdict"])
        direction_ko = _DIRECTION_KO.get(d["direction"], d["direction"])

        print(
            f"\n[DecisionAnalyzer] ══ 최종 투자 판단: {company} ══════════════\n"
            f"  verdict    : {d['verdict'].upper()} ({verdict_ko})\n"
            f"  direction  : {d['direction']} ({direction_ko})\n"
            f"  confidence : {d['confidence']:.4f}  "
            f"({'높음' if d['confidence'] > 0.7 else '중간' if d['confidence'] > 0.4 else '낮음'})\n"
            f"  news_score : {d['news_score']:+.4f}\n"
            f"  sent_score : {d['sentiment_score']:+.4f}\n"
            f"\n  rationale  : {d['rationale']}\n"
            f"\n  reasons (+):"
        )
        for r in d["reasons"]["positive"]:
            print(f"    + {r}")
        print(f"\n  reasons (-):")
        for r in d["reasons"]["negative"]:
            print(f"    - {r}")
        print(f"\n  risk_factors:")
        for r in d["risk_factors"]:
            print(f"    ⚠ {r}")
        print("  " + "═" * 52)
