import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

TITLE_MODEL = "gpt-5-mini"
TITLE_BATCH = 15
TITLE_CONCURRENCY = 10

# PRICE 이벤트 중 LLM 타이틀을 생성할 상위 건수 (중요도 내림차순).
# 나머지는 rule-based 타이틀로 즉시 대체되어 응답 시간을 단축한다.
PRICE_LLM_TOP_N = 50

PRICE_TITLE_SYSTEM = """\
당신은 주식 시장 분석가입니다.
각 가격 이벤트에 대해, 그 이벤트가 발생한 원인을 한 구절로 요약한 타이틀을 생성하십시오.

규칙:
- 타이틀은 15자 이내의 한국어
- 단순 현상 설명이 아닌 원인·배경을 담는다
- 인과 가설이 제공되면 반드시 활용한다
- JSON 배열로만 응답: ["타이틀1", "타이틀2", ...]
- 이벤트 순서와 배열 순서를 반드시 일치시킨다

예시:
- "연준 금리 동결 기대감"
- "실적 쇼크 우려"
- "AI 수혜 기대감으로 갭 상승"
- "기관 대량 매도세"
- "거시 불확실성 고조"
"""

INDEX_PRICE_TITLE_SYSTEM = """\
당신은 글로벌 매크로 시장 분석가입니다.
주가지수 가격 이벤트에 대해, 그 이벤트를 유발한 매크로 원인을 한 구절로 요약한 타이틀을 생성하십시오.

규칙:
- 타이틀은 15자 이내의 한국어
- 개별 기업이 아닌 거시경제·섹터·정책 요인을 담는다
- 인과 가설이 제공되면 반드시 활용한다
- JSON 배열로만 응답: ["타이틀1", "타이틀2", ...]
- 이벤트 순서와 배열 순서를 반드시 일치시킨다

예시:
- "연준 금리 인상 우려"
- "유가 급등 여파"
- "반도체 섹터 조정"
- "인플레이션 재가속"
- "달러 강세 압박"
"""

MACRO_TITLE_SYSTEM = """\
당신은 거시경제 이벤트 분석가입니다.
경제지표 발표 데이터를 읽고, 시장에 미치는 의미를 한 구절로 요약한 타이틀을 생성하십시오.

규칙:
- 타이틀은 15자 이내의 한국어
- 수치 변화의 방향·의미(인상/동결/완화/상회/하회 등)를 담는다
- JSON 배열로만 응답: ["타이틀1", "타이틀2", ...]
- 이벤트 순서와 배열 순서를 반드시 일치시킨다

예시:
- "연준 금리 동결 발표"
- "CPI 예상치 상회"
- "실업률 4년래 최고"
- "긴축 기조 전환 시사"
- "인플레이션 둔화 확인"
"""

OTHER_TITLE_SYSTEM = """\
당신은 주식 투자 이벤트 편집자입니다.
각 이벤트의 type / detail 을 읽고, 그 이벤트를 가장 잘 표현하는 짧은 한국어 타이틀을 생성하십시오.

규칙:
- 타이틀은 12자 이내
- JSON 배열로만 응답: ["타이틀1", "타이틀2", ...]
- 이벤트 순서와 배열 순서를 반드시 일치시킨다
"""

FALLBACK_TITLE: Dict[str, str] = {
    "LOW_52W": "52주 신저가",
    "HIGH_52W": "52주 신고가",
    "SURGE": "급등",
    "PLUNGE": "급락",
    "GAP_UP": "갭 상승",
    "GAP_DOWN": "갭 하락",
    "EARNINGS": "실적 발표",
    "DIVIDEND": "배당",
    "EX_DIVIDEND": "배당락",
    "STOCK_SPLIT": "주식 분할",
    "RIGHTS_OFFERING": "유상증자",
    "BUYBACK": "자사주 취득",
    "BUYBACK_CANCEL": "자사주 소각",
    "MANAGEMENT_CHANGE": "임원 변동",
    "DISCLOSURE": "공시",
    "MERGER_ACQUISITION": "합병·인수",
    "CONTRACT": "계약 체결",
    "MAJOR_EVENT": "주요 공시",
    # MACRO
    "INTEREST_RATE": "기준금리 결정",
    "CPI": "CPI 발표",
    "UNEMPLOYMENT": "실업률 발표",
}


def default_fallback(item: Any) -> str:
    t = getattr(item, "type", "") or ""
    return FALLBACK_TITLE.get(t, t)


def is_fallback_title(event: TimelineEvent) -> bool:
    return event.title == FALLBACK_TITLE.get(event.type, event.type)


def hypothesis_summary(event: TimelineEvent) -> str:
    """인과 가설이 있으면 첫 번째 가설의 핵심 원인 부분을 반환한다."""
    if not event.causality:
        return "(없음)"
    text = event.causality[0].hypothesis
    return text.split("→")[0].strip() if "→" in text else text[:80]


def price_importance(e: TimelineEvent) -> float:
    """PRICE 이벤트의 LLM 타이틀 우선순위 점수. 높을수록 먼저 LLM 처리."""
    score = abs(e.change_pct or 0.0)
    if e.causality:
        score += 100
    if e.type in {"SURGE", "PLUNGE"}:
        score += 50
    if e.type == "LOW_52W":
        score += 30
    if e.type in {"GAP_UP", "GAP_DOWN"}:
        score += 5
    return score


def rule_based_price_title(e: TimelineEvent) -> str:
    """LLM 없이 생성하는 타이틀. 변화율이 있으면 '급등 (+5.2%)' 형태, 없으면 기본 라벨."""
    kind = FALLBACK_TITLE.get(e.type, e.type)
    if e.change_pct is not None:
        sign = "+" if e.change_pct >= 0 else ""
        return f"{kind} ({sign}{e.change_pct:.1f}%)"
    return kind


async def batch_titles(
    items: List[Any],
    system_prompt: str,
    build_line: Callable[[Any], str],
    get_fallback: Optional[Callable[[Any], str]] = None,
) -> List[str]:
    """배치 단위 LLM 호출을 병렬 실행해 타이틀 목록을 반환한다. 실패 시 fallback."""
    if not items:
        return []

    fallback_fn = get_fallback or default_fallback
    fallbacks = [fallback_fn(item) for item in items]
    llm = get_workflow_llm(model=TITLE_MODEL)
    semaphore = asyncio.Semaphore(TITLE_CONCURRENCY)

    async def _run_batch(start: int, batch: List[Any]) -> List[str]:
        lines = "\n".join(f"{j + 1}. {build_line(e)}" for j, e in enumerate(batch))
        async with semaphore:
            try:
                response = await llm.ainvoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=lines),
                ])
                parsed = json.loads(response.content.strip())
                if isinstance(parsed, list) and len(parsed) == len(batch):
                    return [str(t) for t in parsed]
            except Exception as exc:
                logger.warning("[TitleService] 타이틀 배치 생성 실패: %s", exc)
        return fallbacks[start: start + len(batch)]

    tasks = [
        _run_batch(i, items[i: i + TITLE_BATCH])
        for i in range(0, len(items), TITLE_BATCH)
    ]
    results = await asyncio.gather(*tasks)
    titles: List[str] = []
    for sub in results:
        titles.extend(sub)
    return titles


async def enrich_price_titles(timeline: List[TimelineEvent], is_index: bool = False) -> None:
    """PRICE 이벤트 타이틀 생성. is_index=True 시 매크로 관점 프롬프트를 사용한다."""
    candidates = [e for e in timeline if e.category == "PRICE" and is_fallback_title(e)]
    if not candidates:
        return

    system_prompt = INDEX_PRICE_TITLE_SYSTEM if is_index else PRICE_TITLE_SYSTEM
    candidates.sort(key=price_importance, reverse=True)
    llm_targets = candidates[:PRICE_LLM_TOP_N]
    rule_targets = candidates[PRICE_LLM_TOP_N:]

    logger.info(
        "[TitleService] ✦ PRICE 타이틀 (%s): LLM=%d, rule-based=%d (total=%d, cutoff=top %d)",
        "INDEX" if is_index else "EQUITY",
        len(llm_targets), len(rule_targets), len(candidates), PRICE_LLM_TOP_N,
    )

    for e in rule_targets:
        e.title = rule_based_price_title(e)

    if not llm_targets:
        return

    def build_line(e: TimelineEvent) -> str:
        return f"type={e.type} detail={e.detail} | 인과가설: {hypothesis_summary(e)}"

    titles = await batch_titles(llm_targets, system_prompt, build_line)
    for event, title in zip(llm_targets, titles):
        event.title = title
    logger.info("[TitleService] ✦ PRICE 타이틀 생성 완료 (LLM=%d)", len(llm_targets))


async def enrich_other_titles(timeline: List[TimelineEvent]) -> None:
    """CORPORATE / ANNOUNCEMENT 이벤트 타이틀을 생성한다."""
    other_events = [
        e for e in timeline
        if e.category in {"CORPORATE", "ANNOUNCEMENT"} and is_fallback_title(e)
    ]
    if not other_events:
        return

    logger.info("[TitleService] ✦ CORPORATE/ANNOUNCEMENT 타이틀 생성 시작: %d건", len(other_events))

    def build_line(e: TimelineEvent) -> str:
        return f"type={e.type} detail={e.detail}"

    titles = await batch_titles(other_events, OTHER_TITLE_SYSTEM, build_line)
    for event, title in zip(other_events, titles):
        event.title = title
    logger.info("[TitleService] ✦ CORPORATE/ANNOUNCEMENT 타이틀 생성 완료")


async def enrich_macro_titles(timeline: List[TimelineEvent]) -> None:
    """MACRO 이벤트 타이틀을 생성한다."""
    candidates = [e for e in timeline if e.category == "MACRO" and is_fallback_title(e)]
    if not candidates:
        return

    logger.info("[TitleService] ✦ MACRO 타이틀 생성 시작: %d건", len(candidates))

    def build_line(e: TimelineEvent) -> str:
        return f"type={e.type} detail={e.detail}"

    titles = await batch_titles(candidates, MACRO_TITLE_SYSTEM, build_line)
    for event, title in zip(candidates, titles):
        event.title = title
    logger.info("[TitleService] ✦ MACRO 타이틀 생성 완료: %d건", len(candidates))
