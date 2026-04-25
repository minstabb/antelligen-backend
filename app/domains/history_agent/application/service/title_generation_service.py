import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.dashboard.application.usecase.get_economic_events_usecase import (
    macro_fallback_titles,
)
from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.infrastructure.config.settings import get_settings
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

TITLE_MODEL = "gpt-5-mini"


def _settings():
    return get_settings()


# 배치/동시성은 런타임에 get_settings()로 읽는다.
# 하위 호환을 위한 모듈 상수 — import-time에 평가되어 테스트가 monkeypatch할 수 있다.
TITLE_BATCH = _settings().history_title_batch_size
TITLE_CONCURRENCY = _settings().history_title_concurrency

_JSON_RETRY_SUFFIX = (
    "\n\n반드시 JSON 배열만 출력하세요. 추가 설명이나 코드 펜스(```)를 넣지 마세요."
)
_RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0)  # 재시도 시 대기 시간


def _is_rate_limit_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    return "RateLimit" in name or "Throttling" in name or "TooManyRequests" in name


def _classify_error(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, json.JSONDecodeError):
        return "json"
    if _is_rate_limit_error(exc):
        return "rate_limit"
    return "other"

# §13.4 C: PRICE_TITLE_SYSTEM / INDEX_PRICE_TITLE_SYSTEM 제거 (PRICE 카테고리 제거).
# 이상치 봉 causality는 DetectAnomalyBarsUseCase 쪽에서 별도 프롬프트 구성 예정.

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

_NON_MACRO_FALLBACK: Dict[str, str] = {
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
    "ANALYST_UPGRADE": "애널리스트 상향",
    "ANALYST_DOWNGRADE": "애널리스트 하향",
    "EARNINGS_BEAT": "실적 서프라이즈",
    "EARNINGS_MISS": "실적 부진",
    "VIX_SPIKE": "VIX 급변",
    "OIL_SPIKE": "유가 급변",
    "GOLD_SPIKE": "금값 급변",
    "US10Y_SPIKE": "미국채 금리 급변",
    "FX_MOVE": "환율 급변",
    "GEOPOLITICAL_RISK": "지정학 리스크",
    "NEWS": "뉴스",
}

# MACRO fallback은 _SERIES_CONFIG(get_economic_events_usecase)에서 파생 — 단일 소스 유지.
FALLBACK_TITLE: Dict[str, str] = {**_NON_MACRO_FALLBACK, **macro_fallback_titles()}


def default_fallback(item: Any) -> str:
    t = getattr(item, "type", "") or ""
    if t in FALLBACK_TITLE:
        return FALLBACK_TITLE[t]
    label = getattr(item, "label", None)
    return label or t


def is_fallback_title(event: TimelineEvent) -> bool:
    return event.title == FALLBACK_TITLE.get(event.type, event.type)


def hypothesis_summary(event: TimelineEvent) -> str:
    """인과 가설이 있으면 첫 번째 가설의 핵심 원인 부분을 반환한다."""
    if not event.causality:
        return "(없음)"
    text = event.causality[0].hypothesis
    return text.split("→")[0].strip() if "→" in text else text[:80]


# §13.4 C: PRICE 카테고리 제거로 `price_importance`, `rule_based_price_title` 삭제.
# 이상치 봉 판정은 DetectAnomalyBarsUseCase(abs z-score)로 대체.


async def _invoke_llm(llm: Any, system_prompt: str, lines: str) -> str:
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=lines),
    ])
    return response.content.strip()


async def _attempt_batch(
    llm: Any,
    system_prompt: str,
    lines: str,
    expected_count: int,
) -> List[str]:
    """LLM 호출 후 JSON 배열로 파싱한다. 실패는 호출자가 exception으로 받는다."""
    content = await _invoke_llm(llm, system_prompt, lines)
    parsed = json.loads(content)
    if not isinstance(parsed, list):
        raise json.JSONDecodeError("expected list", content, 0)
    if len(parsed) != expected_count:
        # 길이 불일치는 프롬프트 미준수 → JSONDecodeError 취급해 동일 재시도 경로로.
        raise json.JSONDecodeError(
            f"expected {expected_count} items, got {len(parsed)}", content, 0,
        )
    return [str(t) for t in parsed]


async def batch_titles(
    items: List[Any],
    system_prompt: str,
    build_line: Callable[[Any], str],
    get_fallback: Optional[Callable[[Any], str]] = None,
    batch_size: Optional[int] = None,
    concurrency: Optional[int] = None,
) -> List[str]:
    """배치 단위 LLM 호출을 병렬 실행해 타이틀 목록을 반환한다.

    실패 분류와 처리:
    - JSON 파싱 실패 → "JSON 배열만" 지시를 덧붙여 1회 재시도
    - 레이트리밋 → 지수 backoff로 최대 2회 재시도 (1s, 2s)
    - 타임아웃/기타 → 재시도 없이 fallback
    배치 지연은 실패 이유별 카운터와 함께 로깅한다.

    `batch_size`/`concurrency` 미전달 시 settings 기본값(15/10) 사용.
    NEWS 요약처럼 배치 내 LLM 처리 시간이 선형 비례하는 경우 작은 배치 + 병렬이
    유리 → 호출자가 명시 override 가능.
    """
    if not items:
        return []

    fallback_fn = get_fallback or default_fallback
    fallbacks = [fallback_fn(item) for item in items]
    llm = get_workflow_llm(model=TITLE_MODEL)
    settings = _settings()
    if concurrency is None:
        concurrency = settings.history_title_concurrency
    if batch_size is None:
        batch_size = settings.history_title_batch_size
    semaphore = asyncio.Semaphore(concurrency)

    failure_counts: Dict[str, int] = {"timeout": 0, "json": 0, "rate_limit": 0, "other": 0}
    latencies: List[float] = []

    async def _run_batch(start: int, batch: List[Any]) -> List[str]:
        lines = "\n".join(f"{j + 1}. {build_line(e)}" for j, e in enumerate(batch))
        async with semaphore:
            started = time.monotonic()
            try:
                return await _attempt_batch(llm, system_prompt, lines, len(batch))
            except Exception as exc:
                reason = _classify_error(exc)
                failure_counts[reason] += 1

                if reason == "json":
                    try:
                        return await _attempt_batch(
                            llm, system_prompt + _JSON_RETRY_SUFFIX, lines, len(batch),
                        )
                    except Exception as retry_exc:
                        logger.warning(
                            "[TitleService] JSON 재시도 실패: %s → fallback", retry_exc,
                        )

                if reason == "rate_limit":
                    for wait in _RATE_LIMIT_BACKOFF_SECONDS:
                        await asyncio.sleep(wait)
                        try:
                            return await _attempt_batch(
                                llm, system_prompt, lines, len(batch),
                            )
                        except Exception as retry_exc:
                            if not _is_rate_limit_error(retry_exc):
                                logger.warning(
                                    "[TitleService] 레이트리밋 재시도 중 다른 오류: %s",
                                    retry_exc,
                                )
                                break
                    logger.warning("[TitleService] 레이트리밋 재시도 모두 실패 → fallback")

                logger.warning(
                    "[TitleService] 타이틀 배치 실패 (reason=%s): %s", reason, exc,
                )
                return fallbacks[start: start + len(batch)]
            finally:
                latencies.append(time.monotonic() - started)

    tasks = [
        _run_batch(i, items[i: i + batch_size])
        for i in range(0, len(items), batch_size)
    ]
    results = await asyncio.gather(*tasks)
    titles: List[str] = []
    for sub in results:
        titles.extend(sub)

    total_failures = sum(failure_counts.values())
    if latencies:
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95_idx = max(0, int(len(sorted_lat) * 0.95) - 1)
        p95 = sorted_lat[p95_idx]
        logger.info(
            "[TitleService] 타이틀 배치 완료: batches=%d, items=%d, failures=%s, latency_p50=%.2fs, p95=%.2fs",
            len(latencies), len(items), failure_counts, p50, p95,
            extra={
                "llm_op": "title_batch",
                "batches": len(latencies),
                "items": len(items),
                "batch_size": batch_size,
                "concurrency": concurrency,
                "failures": failure_counts,
                "latency_p50_s": round(p50, 3),
                "latency_p95_s": round(p95, 3),
                "sum_latency_s": round(sum(latencies), 3),
            },
        )
    elif total_failures:
        logger.info(
            "[TitleService] 타이틀 배치 실패 집계: %s", failure_counts,
            extra={"llm_op": "title_batch", "failures": failure_counts, "items": len(items)},
        )
    return titles


# §13.4 C: enrich_price_titles 삭제 (PRICE 카테고리 제거).


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
