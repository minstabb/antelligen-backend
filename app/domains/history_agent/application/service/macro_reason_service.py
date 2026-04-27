"""KR2 — MACRO Type B 이벤트 사유 추정 서비스.

5단계 fallback 중 1·4·5 단계 구현 (1단계: 같은 날 Type A cross-ref,
4단계: LLM 추정 with KR3 안전장치, 5단계: "원인 미확인" fallback).
±7일 cross-ref(2단계)와 뉴스 API 검색(3단계)은 후속 PR에서 추가.

KR3 안전장치:
- ① knowledge cutoff 체크 — 이벤트 날짜 > settings.history_macro_reason_cutoff 면 LLM skip
- ② 안전 프롬프트 — "근거 없으면 '원인 미확인'으로 답하라" + 추측 금지 명시
- ③ 출처 강제 — JSON {reason, evidence} 응답 요구. evidence 없으면 reason 도 "원인 미확인"
- ④ 신뢰도 표시 — cross-ref 매칭은 HIGH, LLM 추정은 LOW
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any, List, Optional

import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.title_generation_service import (
    classify_macro_type,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

_UNKNOWN_REASON = "원인 미확인"
_CACHE_VERSION = "v1"
_CACHE_TTL_SEC = 90 * 24 * 60 * 60  # 90 days

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


def _parse_cutoff(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning(
            "[MacroReason] history_macro_reason_cutoff 파싱 실패 — LLM 호출 전부 skip: value=%r",
            value,
        )
        return None


def _cache_key(event: TimelineEvent) -> str:
    fp = f"{event.type}|{event.date.isoformat()}|{event.detail}"
    h = hashlib.sha256(fp.encode()).hexdigest()[:16]
    return f"macro_reason:{_CACHE_VERSION}:{h}"


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


async def enrich_type_b_reasons(
    timeline: List[TimelineEvent],
    redis: Optional[aioredis.Redis] = None,
) -> None:
    """Type B MACRO 이벤트의 사유를 채운다.

    1. KR1 분류 적용 — 모든 MACRO 이벤트의 macro_type 필드 채움
    2. Type B 이벤트에 대해 같은 날 Type A cross-ref → 매칭 시 HIGH 신뢰도로 기록
    3. 미매칭 이벤트는 KR3 안전장치 적용한 LLM 추정 (cutoff 체크, 출처 강제)
    4. 미해결은 reason=None 으로 두고 frontend 에서 "원인 미확인" UI 처리
    """
    macro_events = [e for e in timeline if e.category == "MACRO"]
    if not macro_events:
        return

    # KR1 — 모든 MACRO 이벤트에 분류 라벨 부여.
    for ev in macro_events:
        ev.macro_type = classify_macro_type(ev)

    type_a_by_date = {}
    for ev in macro_events:
        if ev.macro_type == "TYPE_A":
            type_a_by_date.setdefault(ev.date, []).append(ev)

    type_b_events = [e for e in macro_events if e.macro_type == "TYPE_B"]
    if not type_b_events:
        return

    # 1단계 — 같은 날 Type A cross-ref.
    needs_llm: List[TimelineEvent] = []
    cross_ref_hits = 0
    for ev in type_b_events:
        same_day_a = type_a_by_date.get(ev.date)
        if same_day_a:
            primary = same_day_a[0]
            ev.reason = f"{primary.title} 영향"
            ev.reason_confidence = "HIGH"
            ev.reason_evidence = primary.title
            cross_ref_hits += 1
            continue
        needs_llm.append(ev)

    if not needs_llm:
        logger.info(
            "[MacroReason] ✦ Type B 사유 — 전체 cross-ref 매칭: %d건",
            cross_ref_hits,
        )
        return

    # 4단계 — LLM 추정 with KR3 안전장치.
    settings = get_settings()
    cutoff = _parse_cutoff(settings.history_macro_reason_cutoff)

    # cache lookup
    cache_keys = [_cache_key(e) for e in needs_llm]
    cached_values: List[Optional[bytes]] = [None] * len(needs_llm)
    if redis is not None:
        try:
            cached_values = await redis.mget(cache_keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MacroReason] cache mget 실패 — miss 로 진행: %s", exc,
            )
            cached_values = [None] * len(needs_llm)

    miss_events: List[TimelineEvent] = []
    miss_keys: List[str] = []
    cache_hits = 0
    for ev, cached, key in zip(needs_llm, cached_values, cache_keys):
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
                "[MacroReason] cache row 파싱 실패 — miss 로 진행: key=%s err=%s",
                key, exc,
            )
            miss_events.append(ev)
            miss_keys.append(key)

    # cutoff skip — LLM 호출 자체를 회피.
    skipped_by_cutoff = 0
    llm_targets: List[TimelineEvent] = []
    llm_target_keys: List[str] = []
    for ev, key in zip(miss_events, miss_keys):
        if cutoff is not None and ev.date > cutoff:
            ev.reason = None
            ev.reason_confidence = None
            ev.reason_evidence = None
            skipped_by_cutoff += 1
            continue
        llm_targets.append(ev)
        llm_target_keys.append(key)

    if not llm_targets:
        logger.info(
            "[MacroReason] ✦ Type B 사유 완료 (LLM skip): cross_ref=%d cache=%d cutoff_skip=%d",
            cross_ref_hits, cache_hits, skipped_by_cutoff,
        )
        return

    logger.info(
        "[MacroReason] ✦ Type B 사유 LLM 호출: targets=%d (cross_ref=%d cache=%d cutoff_skip=%d)",
        len(llm_targets), cross_ref_hits, cache_hits, skipped_by_cutoff,
    )

    settings_model = settings.history_title_llm_model
    llm = get_workflow_llm(model=settings_model)
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
            ev.reason = None
            ev.reason_confidence = None
            ev.reason_evidence = None
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
                    pipe.setex(key, _CACHE_TTL_SEC, payload)
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[MacroReason] cache 저장 실패 (graceful): %s", exc,
            )

    logger.info(
        "[MacroReason] ✦ Type B 사유 완료: cross_ref=%d cache=%d cutoff_skip=%d resolved=%d unknown=%d",
        cross_ref_hits, cache_hits, skipped_by_cutoff, resolved_count, unknown_count,
    )
