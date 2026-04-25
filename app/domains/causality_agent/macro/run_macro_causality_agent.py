"""INDEX causality Phase B — LLM 기반 매크로 가설 생성.

T2-1 Phase A(규칙 기반)가 매핑하지 못한 INDEX SURGE/PLUNGE 이벤트에 대해
주변 MACRO 발표·섹터 로테이션·뉴스 맥락을 종합해 짧은 가설을 생성한다.

런칭 전 `tests/domains/causality_agent/macro/fixtures/` 골든셋 30건을 통과해야
`settings.index_causality_llm_enabled` 플래그를 켤 수 있다.

현재 구현은 최소 버전으로, FRED 윈도우 요약을 컨텍스트로 LLM 한 번 호출한다.
"""

import json
import logging
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.history_agent.application.response.timeline_response import (
    HypothesisResult,
    TimelineEvent,
)
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

_MODEL = "gpt-5-mini"
_MACRO_WINDOW_DAYS = 14

_MACRO_CAUSALITY_SYSTEM = """\
당신은 글로벌 매크로 리스크 분석가입니다.
주가지수의 급등락 이벤트와 주변 경제 지표·가격 흐름을 보고,
그 이벤트의 원인을 설명하는 짧은 가설을 1~2개 생성하십시오.

규칙:
- 각 가설은 한 문장 한국어(30자 내외).
- "원인 → 결과" 형식을 유지한다. 예: "9월 CPI 서프라이즈 → 기술주 매도세".
- 구체적 발표명/수치/날짜 오프셋을 활용한다 (예: "9월 FOMC 25bp 인상").
- 컨텍스트에서 확인되지 않는 추측은 제외한다.
- JSON 배열로만 응답: [{"hypothesis": "...", "supporting": ["fred:FEDFUNDS"]}].
"""


def _event_context(price_event: TimelineEvent, timeline: List[TimelineEvent]) -> str:
    from datetime import timedelta

    window_start = price_event.date - timedelta(days=_MACRO_WINDOW_DAYS)
    window_end = price_event.date + timedelta(days=_MACRO_WINDOW_DAYS)
    nearby = [
        e for e in timeline
        if e.category == "MACRO"
        and window_start <= e.date <= window_end
    ]
    nearby_sorted = sorted(nearby, key=lambda e: e.date)
    lines = [
        f"PRICE: {price_event.date} {price_event.type} "
        f"({price_event.change_pct:+.2f}%)" if price_event.change_pct is not None
        else f"PRICE: {price_event.date} {price_event.type}"
    ]
    for m in nearby_sorted:
        offset = (m.date - price_event.date).days
        change = f"{m.change_pct:+.2f}%p" if m.change_pct is not None else "n/a"
        lines.append(f"MACRO: {m.date} {m.type} ({change}, D{offset:+d}) — {m.title}")
    return "\n".join(lines)


async def run_macro_causality_agent(
    ticker: str,
    event: TimelineEvent,
    timeline: List[TimelineEvent],
) -> List[HypothesisResult]:
    context = _event_context(event, timeline)
    try:
        llm = get_workflow_llm(model=_MODEL)
        response = await llm.ainvoke([
            SystemMessage(content=_MACRO_CAUSALITY_SYSTEM),
            HumanMessage(content=f"지수: {ticker}\n\n{context}"),
        ])
        raw = response.content.strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return []
        hypotheses: List[HypothesisResult] = []
        for item in parsed:
            if not isinstance(item, dict) or "hypothesis" not in item:
                continue
            hypotheses.append(HypothesisResult(
                hypothesis=str(item["hypothesis"]),
                supporting_tools_called=[
                    str(s) for s in item.get("supporting", [])
                ] or ["llm:macro_causality"],
            ))
        return hypotheses
    except Exception as exc:
        logger.warning(
            "[MacroCausality] 실패: ticker=%s, event=%s (%s) — %s",
            ticker, event.type, event.date, exc,
        )
        return []
