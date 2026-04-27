"""KR2 — MACRO Type B 이벤트 사유 추정 서비스.

5단계 fallback 전체 구현 (1·2·3·4·5 단계).
이전 슬라이스에서 1·4·5 단계만 있었고, 본 슬라이스에서 2·3 단계가 추가됐다.

KR3 안전장치(LLM 호출 시):
- ① knowledge cutoff 체크 — 이벤트 날짜 > settings.history_macro_reason_cutoff 면 LLM skip
- ② 안전 프롬프트 — "근거 없으면 '원인 미확인'으로 답하라" + 추측 금지 명시
- ③ 출처 강제 — JSON {reason, evidence} 응답 요구. evidence 없으면 reason 도 "원인 미확인"
- ④ 신뢰도 표시 — cross-ref 같은 날=HIGH / cross-ref ±7일=MEDIUM / 뉴스 검색=MEDIUM / LLM=LOW
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.history_agent.application.port.out.macro_news_search_port import (
    MacroNewsSearchPort,
)
from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.title_generation_service import (
    classify_macro_type,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

_UNKNOWN_REASON = "원인 미확인"

# LLM 결과 캐시.
_LLM_CACHE_VERSION = "v1"
_LLM_CACHE_TTL_SEC = 90 * 24 * 60 * 60  # 90 days

# 뉴스 검색 결과 캐시(외부 API 비용 회피용). LLM 캐시와 분리.
_NEWS_CACHE_VERSION = "v1"
_NEWS_CACHE_TTL_SEC = 7 * 24 * 60 * 60  # 7 days — 뉴스는 쇠도가 빨라 짧게

# KR2-(2) — Type A 가 같은 날 없을 때 ±N일 윈도우 안에서 검색.
_CROSS_REF_WINDOW_DAYS = 7

# KR2-(3) — 뉴스 검색 윈도우(좁게: 정확도 우선).
_NEWS_WINDOW_DAYS = 2

# KR2-(3) — Type B 매크로 이벤트별 GDELT 검색 키워드.
# 영문 키워드 위주(GDELT는 글로벌·영문 우선). 키 미정의 type 은 단계 skip 후 LLM 진입.
_MACRO_TYPE_NEWS_KEYWORDS: Dict[str, str] = {
    "VIX_SPIKE": "stock market volatility VIX surge",
    "OIL_SPIKE": "crude oil price",
    "GOLD_SPIKE": "gold price",
    "US10Y_SPIKE": "US treasury yield",
    "FX_MOVE": "US dollar exchange rate",
    "GEOPOLITICAL_RISK": "geopolitical crisis conflict",
}

REASON_SYSTEM_PROMPT = """\
당신은 금융 시장 분석 보조입니다. 다음 매크로 이벤트(VIX 급등, 유가 급변 등 시장 결과 이벤트)의 사유를 추정하세요.

규칙:
- 명확한 근거(특정 사건명, 정책 발표명, 지표 발표명)가 없다면 "원인 미확인"으로 답하세요.
- 추측이나 일반론(경기 둔화 우려, 인플레이션 우려 등) 은 금지합니다.
- 근거를 제시할 수 없으면 모른다고 답하는 것이 정확한 답을 만드는 것보다 중요합니다.
- 응답은 JSON 객체만 출력. 설명·코드 펜스 금지.
- JSON 스키마:
  {"reason": "한 문장 사유" 또는 "원인 미확인", "evidence": "특정 사건명/발표명" 또는 null}
- evidence 가 null 이면 reason 은 반드시 "원인 미확인" 이어야 합니다.
"""


# ── 헬퍼 ────────────────────────────────────────────────────


def _parse_cutoff(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning(
            "[MacroReason] history_macro_reason_cutoff 파싱 실패 — LLM 호출 전부 skip: value=%r",
            value,
        )
        return None


def _llm_cache_key(event: TimelineEvent) -> str:
    fp = f"{event.type}|{event.date.isoformat()}|{event.detail}"
    h = hashlib.sha256(fp.encode()).hexdigest()[:16]
    return f"macro_reason:{_LLM_CACHE_VERSION}:{h}"


def _news_cache_key(event_type: str, event_date: date) -> str:
    fp = f"{event_type}|{event_date.isoformat()}"
    h = hashlib.sha256(fp.encode()).hexdigest()[:16]
    return f"macro_reason_news:{_NEWS_CACHE_VERSION}:{h}"


def _set_reason(
    ev: TimelineEvent,
    reason: Optional[str],
    confidence: Optional[str],
    evidence: Optional[str],
) -> None:
    ev.reason = reason
    ev.reason_confidence = confidence
    ev.reason_evidence = evidence


# ── 1단계: 같은 날 Type A cross-ref (HIGH) ─────────────────


def _resolve_same_day_cross_ref(
    type_b_events: List[TimelineEvent],
    type_a_by_date: Dict[date, List[TimelineEvent]],
) -> tuple[List[TimelineEvent], int]:
    pending: List[TimelineEvent] = []
    hits = 0
    for ev in type_b_events:
        same_day_a = type_a_by_date.get(ev.date)
        if same_day_a:
            primary = same_day_a[0]
            _set_reason(
                ev,
                reason=f"{primary.title} 영향",
                confidence="HIGH",
                # url 이 있으면 frontend 가 "사유 출처 보기" 핑크 링크로 노출. 없으면 title fallback.
                evidence=primary.url or primary.title,
            )
            hits += 1
            continue
        pending.append(ev)
    return pending, hits


# ── 2단계: ±7일 Type A cross-ref (MEDIUM) ─────────────────


def _resolve_window_cross_ref(
    pending: List[TimelineEvent],
    type_a_events: List[TimelineEvent],
) -> tuple[List[TimelineEvent], int]:
    """가장 가까운 Type A(절대 날짜 차이 ≤ 7일)를 reason 으로 채운다.

    동률이면 더 이른(과거) Type A 우선. detail 에 일자 차이를 표기해 카드 UI 가
    "발표일 N일 전/후" 맥락을 표시하도록 정보 보존.
    """
    if not type_a_events:
        return pending, 0

    sorted_a = sorted(type_a_events, key=lambda e: e.date)
    next_pending: List[TimelineEvent] = []
    hits = 0
    for ev in pending:
        closest: Optional[TimelineEvent] = None
        closest_diff: int = _CROSS_REF_WINDOW_DAYS + 1
        for a in sorted_a:
            diff = abs((a.date - ev.date).days)
            if diff > _CROSS_REF_WINDOW_DAYS:
                continue
            if diff < closest_diff:
                closest = a
                closest_diff = diff
        if closest is not None:
            delta_days = (ev.date - closest.date).days
            if delta_days > 0:
                window_label = f"{delta_days}일 후"
            elif delta_days < 0:
                window_label = f"{-delta_days}일 전"
            else:  # pragma: no cover — 같은 날은 1단계에서 이미 처리됨.
                window_label = "당일"
            _set_reason(
                ev,
                reason=f"{closest.title} {window_label} 영향",
                confidence="MEDIUM",
                # url 이 있으면 frontend 핑크 링크 노출. 없으면 title fallback.
                evidence=closest.url or closest.title,
            )
            hits += 1
            continue
        next_pending.append(ev)
    return next_pending, hits


# ── 3단계: GDELT 뉴스 검색 (MEDIUM) ───────────────────────


async def _fetch_news_with_cache(
    *,
    port: MacroNewsSearchPort,
    redis: Optional[aioredis.Redis],
    keyword: str,
    event_type: str,
    event_date: date,
) -> Optional[List[Dict[str, Any]]]:
    """뉴스 검색 + Redis 캐시. 외부 API 비용 회피.

    None 반환 = 캐시·검색 모두 실패(상위 단계가 skip 처리). 빈 리스트는 정상 응답.
    """
    cache_key = _news_cache_key(event_type, event_date)
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                payload = cached.decode() if isinstance(cached, (bytes, bytearray)) else cached
                return json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MacroReason] news cache get 실패 — fresh fetch: %s", exc,
            )

    start = event_date - timedelta(days=_NEWS_WINDOW_DAYS)
    end = event_date + timedelta(days=_NEWS_WINDOW_DAYS)
    try:
        articles = await port.search(keyword=keyword, start_date=start, end_date=end)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[MacroReason] news 검색 실패 — skip: type=%s date=%s err=%s",
            event_type, event_date, exc,
        )
        return None

    if redis is not None:
        try:
            await redis.setex(
                cache_key, _NEWS_CACHE_TTL_SEC, json.dumps(articles, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MacroReason] news cache set 실패 (graceful): %s", exc,
            )
    return articles


async def _resolve_news_search(
    pending: List[TimelineEvent],
    *,
    port: MacroNewsSearchPort,
    redis: Optional[aioredis.Redis],
) -> tuple[List[TimelineEvent], int]:
    next_pending: List[TimelineEvent] = []
    hits = 0
    for ev in pending:
        keyword = _MACRO_TYPE_NEWS_KEYWORDS.get(ev.type)
        if not keyword:
            next_pending.append(ev)
            continue

        articles = await _fetch_news_with_cache(
            port=port, redis=redis,
            keyword=keyword, event_type=ev.type, event_date=ev.date,
        )
        if not articles:
            next_pending.append(ev)
            continue

        first = articles[0]
        title = (first.get("title") or "").strip()
        url = (first.get("url") or "").strip()
        if not title:
            next_pending.append(ev)
            continue

        _set_reason(
            ev,
            reason=title,
            confidence="MEDIUM",
            evidence=url or title,
        )
        hits += 1
    return next_pending, hits


# ── 4단계: LLM 추정 (LOW with KR3 안전장치) ────────────────


async def _invoke_llm_for_reason(llm: Any, event: TimelineEvent) -> Optional[dict]:
    user_line = (
        f"date={event.date.isoformat()} type={event.type} detail={event.detail}"
    )
    response = await llm.ainvoke([
        SystemMessage(content=REASON_SYSTEM_PROMPT),
        HumanMessage(content=user_line),
    ])
    content = (response.content or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[MacroReason] LLM JSON 파싱 실패 — 미확인 처리: type=%s date=%s err=%s",
            event.type, event.date, exc,
        )
        return None
    if not isinstance(parsed, dict):
        return None
    reason = parsed.get("reason")
    evidence = parsed.get("evidence")
    # KR3-③ — evidence 없으면 reason 강제 무효화.
    if not evidence or not isinstance(evidence, str) or not evidence.strip():
        return {"reason": _UNKNOWN_REASON, "evidence": None}
    if not isinstance(reason, str) or not reason.strip() or reason.strip() == _UNKNOWN_REASON:
        return {"reason": _UNKNOWN_REASON, "evidence": None}
    return {"reason": reason.strip(), "evidence": evidence.strip()}


async def _resolve_llm_with_cache(
    pending: List[TimelineEvent],
    *,
    redis: Optional[aioredis.Redis],
) -> tuple[int, int, int, int]:
    """LLM 단계 처리. 미해결 이벤트는 reason None 으로 둠 (5단계 fallback).

    Returns: (cache_hits, cutoff_skipped, llm_resolved, llm_unknown)
    """
    if not pending:
        return 0, 0, 0, 0

    settings = get_settings()
    cutoff = _parse_cutoff(settings.history_macro_reason_cutoff)

    cache_keys = [_llm_cache_key(e) for e in pending]
    cached_values: List[Optional[bytes]] = [None] * len(pending)
    if redis is not None:
        try:
            cached_values = await redis.mget(cache_keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MacroReason] llm cache mget 실패 — miss 로 진행: %s", exc,
            )
            cached_values = [None] * len(pending)

    miss_events: List[TimelineEvent] = []
    miss_keys: List[str] = []
    cache_hits = 0
    for ev, cached, key in zip(pending, cached_values, cache_keys):
        if cached is None:
            miss_events.append(ev)
            miss_keys.append(key)
            continue
        try:
            payload = json.loads(
                cached.decode() if isinstance(cached, (bytes, bytearray)) else cached
            )
            ev.reason = payload.get("reason")
            ev.reason_confidence = payload.get("reason_confidence")
            ev.reason_evidence = payload.get("reason_evidence")
            cache_hits += 1
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.warning(
                "[MacroReason] llm cache row 파싱 실패 — miss 로 진행: key=%s err=%s",
                key, exc,
            )
            miss_events.append(ev)
            miss_keys.append(key)

    cutoff_skipped = 0
    llm_targets: List[TimelineEvent] = []
    llm_target_keys: List[str] = []
    for ev, key in zip(miss_events, miss_keys):
        if cutoff is not None and ev.date > cutoff:
            _set_reason(ev, None, None, None)
            cutoff_skipped += 1
            continue
        llm_targets.append(ev)
        llm_target_keys.append(key)

    if not llm_targets:
        return cache_hits, cutoff_skipped, 0, 0

    llm = get_workflow_llm(model=settings.history_title_llm_model)
    semaphore = asyncio.Semaphore(settings.history_title_concurrency)

    async def _run_one(ev: TimelineEvent) -> Optional[dict]:
        async with semaphore:
            try:
                return await _invoke_llm_for_reason(llm, ev)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[MacroReason] LLM 호출 실패 — 미확인 처리: type=%s date=%s err=%s",
                    ev.type, ev.date, exc,
                )
                return None

    results = await asyncio.gather(*[_run_one(ev) for ev in llm_targets])

    save_pairs: List[tuple[str, str]] = []
    unknown_count = 0
    resolved_count = 0
    for ev, key, result in zip(llm_targets, llm_target_keys, results):
        if result is None or result.get("reason") == _UNKNOWN_REASON:
            _set_reason(ev, None, None, None)
            unknown_count += 1
            continue
        ev.reason = result["reason"]
        ev.reason_confidence = "LOW"
        ev.reason_evidence = result["evidence"]
        resolved_count += 1
        save_pairs.append((
            key,
            json.dumps({
                "reason": ev.reason,
                "reason_confidence": ev.reason_confidence,
                "reason_evidence": ev.reason_evidence,
            }, ensure_ascii=False),
        ))

    if redis is not None and save_pairs:
        try:
            async with redis.pipeline(transaction=False) as pipe:
                for key, payload in save_pairs:
                    pipe.setex(key, _LLM_CACHE_TTL_SEC, payload)
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MacroReason] llm cache 저장 실패 (graceful): %s", exc,
            )

    return cache_hits, cutoff_skipped, resolved_count, unknown_count


# ── 진입점 ──────────────────────────────────────────────────


async def enrich_type_b_reasons(
    timeline: List[TimelineEvent],
    redis: Optional[aioredis.Redis] = None,
    news_search_port: Optional[MacroNewsSearchPort] = None,
) -> None:
    """Type B MACRO 이벤트의 사유를 채운다. 5단계 fallback 흐름:

    1. KR1 분류 — 모든 MACRO 이벤트의 macro_type 채움
    2. 같은 날 Type A cross-ref → HIGH
    3. ±7일 Type A cross-ref → MEDIUM (가장 가까운 Type A)
    4. 뉴스 검색(GDELT 등) → MEDIUM
    5. LLM 추정 with KR3 안전장치 → LOW
    6. 미해결은 reason=None (frontend 가 "원인 미확인" 표시)

    `news_search_port` 가 None 이면 4단계는 skip 되고 5단계로 직진. DI 미주입
    환경(테스트 등)에서도 1·2·5 단계는 정상 동작.
    """
    macro_events = [e for e in timeline if e.category == "MACRO"]
    if not macro_events:
        return

    # KR1 — 모든 MACRO 이벤트에 분류 라벨 부여.
    for ev in macro_events:
        ev.macro_type = classify_macro_type(ev)

    type_a_events = [e for e in macro_events if e.macro_type == "TYPE_A"]
    type_a_by_date: Dict[date, List[TimelineEvent]] = {}
    for ev in type_a_events:
        type_a_by_date.setdefault(ev.date, []).append(ev)

    type_b_events = [e for e in macro_events if e.macro_type == "TYPE_B"]
    if not type_b_events:
        return

    pending, same_day_hits = _resolve_same_day_cross_ref(type_b_events, type_a_by_date)
    pending, window_hits = _resolve_window_cross_ref(pending, type_a_events)

    news_hits = 0
    if pending and news_search_port is not None:
        pending, news_hits = await _resolve_news_search(
            pending, port=news_search_port, redis=redis,
        )

    cache_hits, cutoff_skipped, llm_resolved, llm_unknown = await _resolve_llm_with_cache(
        pending, redis=redis,
    )

    logger.info(
        "[MacroReason] ✦ Type B 사유 완료: same_day=%d window=%d news=%d "
        "llm_cache=%d cutoff_skip=%d llm_resolved=%d llm_unknown=%d",
        same_day_hits, window_hits, news_hits,
        cache_hits, cutoff_skipped, llm_resolved, llm_unknown,
    )
