"""
validate_hypotheses 노드 (KR3 가드레일).

generate_hypotheses 노드가 생성한 가설 리스트에 다음 4가지 금지 규칙을 적용한다.

1. 단정적 표현 금지 ("때문이다", "확실히" 등) → confidence="LOW" 다운그레이드
2. 매수/매도 추천 금지 ("매수", "매도", "추천", "유망") → 해당 가설 제거
3. 단일 원인 단순화 금지 (가설 ≤ 1개 또는 모든 가설이 단일 layer) → 전체 LOW
4. 인과/상관 혼동 금지 (인과 어휘 + evidence 부재) → confidence="LOW" 다운그레이드

LLM 재생성은 비용이 크므로 본 노드는 정규식 기반 후처리 + LOW 다운그레이드만 수행한다.
프론트엔드(AnomalyCausalityPopup)는 LOW 가설을 회색으로 시각적 구분하므로,
사용자가 신뢰할 수 없는 추정을 즉시 식별할 수 있다.
"""
import logging
import re
from typing import Any, Dict, List

from app.domains.causality_agent.domain.state.causality_agent_state import CausalityAgentState

logger = logging.getLogger(__name__)

# (1) 단정 어휘 — "때문에"는 인과 표현이라 별도. "때문이다/때문임"만 단정으로 본다.
_ASSERTIVE_PATTERNS = [
    re.compile(r"확실히|분명히|반드시|필연적|명백히"),
    re.compile(r"틀림\s*없[이다음]"),
    re.compile(r"때문이[다며임]"),
]

# (2) 매수/매도 추천 — 검출 시 가설 제거.
_RECOMMENDATION_PATTERNS = [
    re.compile(r"매수\s*(추천|권장|의견|타이밍)?"),
    re.compile(r"매도\s*(추천|권장|의견|타이밍)?"),
    re.compile(r"(사야|팔아야)\s*(한다|합니다|할\s*시점)?"),
    re.compile(r"(투자|매매)\s*(추천|권장)"),
    re.compile(r"유망(하다|합니다|한\s*종목)"),
    re.compile(r"\b(buy|sell)\s+(this|it|now|the\s+stock)\b", re.IGNORECASE),
]

# (4) 인과/상관 혼동 — 인과 어휘가 있는데 evidence 가 비면 LOW 다운그레이드.
_CAUSAL_PATTERNS = [
    re.compile(r"때문에"),
    re.compile(r"이로\s*인해"),
    re.compile(r"에\s*따라\s*(하락|상승|반등|급등|급락)"),
]

_VIOLATION_TAG = "guardrail"


def _has_assertive(text: str) -> bool:
    return any(p.search(text) for p in _ASSERTIVE_PATTERNS)


def _has_recommendation(text: str) -> bool:
    return any(p.search(text) for p in _RECOMMENDATION_PATTERNS)


def _has_causal_without_evidence(h: Dict[str, Any]) -> bool:
    text = h.get("hypothesis", "")
    if not any(p.search(text) for p in _CAUSAL_PATTERNS):
        return False
    evidence = h.get("evidence")
    return not evidence or not str(evidence).strip()


def _downgrade(h: Dict[str, Any], reason: str) -> None:
    h["confidence"] = "LOW"
    logger.info(
        "[CausalityAgent] [Validate] downgrade: reason=%s, h=%s",
        reason,
        h.get("hypothesis", "")[:60],
    )


async def validate_hypotheses(state: CausalityAgentState) -> Dict[str, Any]:
    """KR3 4가지 금지 규칙 후처리. hypotheses 와 errors 만 갱신해 반환한다."""
    hypotheses_in: List[Dict[str, Any]] = list(state.get("hypotheses", []))
    errors = list(state.get("errors", []))

    kept: List[Dict[str, Any]] = []
    removed_count = 0

    for h in hypotheses_in:
        text = h.get("hypothesis", "")

        # (2) 매수/매도 추천 → 제거
        if _has_recommendation(text):
            removed_count += 1
            errors.append(f"{_VIOLATION_TAG}:recommendation_removed")
            continue

        # (1) 단정 어휘 → LOW
        if _has_assertive(text):
            _downgrade(h, "assertive_lexicon")
            errors.append(f"{_VIOLATION_TAG}:assertive_lexicon")

        # (4) 인과 어휘 + evidence 부재 → LOW
        if _has_causal_without_evidence(h):
            _downgrade(h, "causal_without_evidence")
            errors.append(f"{_VIOLATION_TAG}:causal_without_evidence")

        kept.append(h)

    # (3) 단일 원인 단순화 — 가설 1개 이하 또는 layer 단일이면 전체 LOW
    if len(kept) <= 1:
        for h in kept:
            _downgrade(h, "simplification_too_few")
        if kept:
            errors.append(f"{_VIOLATION_TAG}:simplification_too_few")
    else:
        layers = {(h.get("layer") or "SUPPORTING") for h in kept}
        if len(layers) <= 1:
            for h in kept:
                _downgrade(h, "simplification_single_layer")
            errors.append(f"{_VIOLATION_TAG}:simplification_single_layer")

    logger.info(
        "[CausalityAgent] [Validate] 적용: 입력=%d, 제거=%d, 최종=%d",
        len(hypotheses_in),
        removed_count,
        len(kept),
    )

    return {
        "hypotheses": kept,
        "errors": errors,
    }
