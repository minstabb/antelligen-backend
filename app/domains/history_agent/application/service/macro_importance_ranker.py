"""매크로 이벤트의 역사적 중요도를 LLM으로 점수화한다.

- 입력: MACRO·MACRO_CONTEXT 카테고리 TimelineEvent 리스트
- 출력: 각 이벤트의 `importance_score` (0.0~1.0) 주석 주입
- 캐시: event_enrichments 테이블에 (ticker, date, type, detail_hash) 키로 점수 영속화
  이미 저장된 점수는 LLM 호출 대상에서 제외하여 재요청 비용을 제거
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from app.domains.history_agent.application.port.out.event_enrichment_repository_port import (
    EventEnrichmentRepositoryPort,
)
from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.application.service.title_generation_service import (
    TITLE_MODEL,
)
from app.domains.history_agent.domain.entity.event_enrichment import (
    EventEnrichment,
    compute_detail_hash,
)
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

MACRO_IMPORTANCE_SYSTEM = """\
당신은 금융시장사(史) 분석가입니다.
각 매크로 이벤트가 '시장사에 남을 만한 역사적 중요도'를 0.0~1.0 범위로 점수화하십시오.

점수 기준:
- 1.0: 위기·체제 전환급 (리먼 파산, 팬데믹 서킷브레이커, 전면전 개시, 긴급 금리 인하)
- 0.8~0.9: 주요 정책 전환 / 대형 은행 파산 / 대규모 제재·관세
- 0.5~0.7: 서프라이즈 수준의 지표 변화, 의미 있는 정책 결정
- 0.3~0.4: 방향 전환은 있으나 시장 영향 제한적인 변화
- 0.0~0.2: 일상 릴리스, 노이즈 수준 변동

규칙:
- JSON 배열로만 응답: [0.73, 0.12, 0.95, ...]
- 이벤트 순서와 배열 순서를 반드시 일치시킨다
- 각 값은 0.0~1.0 사이의 소수 (최대 2자리)
- 추가 설명 금지
"""

_BATCH_SIZE = 20
_CONCURRENCY = 4
_JSON_RETRY_SUFFIX = (
    "\n\n반드시 0.0~1.0 사이 숫자로 구성된 JSON 배열만 출력하세요. 설명·코드펜스 금지."
)


def _build_line(idx: int, event: TimelineEvent) -> str:
    change = f" Δ{event.change_pct:+.2f}" if event.change_pct is not None else ""
    return f"{idx + 1}. type={event.type} date={event.date.isoformat()}{change} detail={event.detail[:200]}"


async def _invoke_llm(llm: Any, system_prompt: str, lines: str) -> str:
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=lines),
    ])
    return response.content.strip()


def _parse_scores(content: str, expected: int) -> List[float]:
    parsed = json.loads(content)
    if not isinstance(parsed, list):
        raise json.JSONDecodeError("expected list", content, 0)
    if len(parsed) != expected:
        raise json.JSONDecodeError(
            f"expected {expected} items, got {len(parsed)}", content, 0,
        )
    return [max(0.0, min(1.0, float(v))) for v in parsed]


async def _score_batch(
    llm: Any, batch: List[TimelineEvent], sem: asyncio.Semaphore
) -> List[float]:
    lines = "\n".join(_build_line(i, e) for i, e in enumerate(batch))
    async with sem:
        try:
            content = await _invoke_llm(llm, MACRO_IMPORTANCE_SYSTEM, lines)
            return _parse_scores(content, len(batch))
        except json.JSONDecodeError as exc:
            logger.warning("[MacroImportance] JSON 파싱 실패, 재시도: %s", exc)
            try:
                content = await _invoke_llm(
                    llm, MACRO_IMPORTANCE_SYSTEM + _JSON_RETRY_SUFFIX, lines,
                )
                return _parse_scores(content, len(batch))
            except Exception as retry_exc:
                logger.warning("[MacroImportance] 재시도 실패 → 중립값 할당: %s", retry_exc)
                return [0.3] * len(batch)
        except Exception as exc:
            logger.warning("[MacroImportance] 점수화 실패 → 중립값 할당: %s", exc)
            return [0.3] * len(batch)


def _build_cache_key(
    scope_ticker: str, event: TimelineEvent
) -> Tuple[str, Any, str, str]:
    return (
        scope_ticker,
        event.date,
        event.type,
        compute_detail_hash(event.detail),
    )


class MacroImportanceRanker:
    """LLM 기반 매크로 이벤트 중요도 랭커 + DB 점수 캐시."""

    def __init__(
        self,
        enrichment_repo: EventEnrichmentRepositoryPort,
        scope_ticker: str = "__MACRO__",
    ):
        self._repo = enrichment_repo
        # event_enrichments는 ticker-scoped 테이블이라 매크로 전용 고정 키를 쓴다.
        self._scope_ticker = scope_ticker

    async def score(self, events: List[TimelineEvent]) -> None:
        """events에 importance_score를 in-place로 채운다. 실패 시 기본값 0.3.

        이미 점수가 설정된 이벤트(curated 등)는 건드리지 않는다.
        """
        if not events:
            return

        targets = [e for e in events if e.importance_score is None]
        if not targets:
            return

        start = time.monotonic()
        keys = [_build_cache_key(self._scope_ticker, e) for e in targets]
        logger.info(
            "[MacroImportance] 시작: targets=%d (scope=%s)",
            len(targets), self._scope_ticker,
        )
        try:
            cached = await self._repo.find_by_keys(keys)
        except Exception as exc:  # noqa: BLE001
            # DB 스키마 미일치(alembic 미실행) 또는 일시 장애로 find_by_keys 실패.
            # 세션이 abort 상태일 수 있으니 호출부가 rollback할 수 있도록 재전파한다.
            logger.error(
                "[MacroImportance] find_by_keys 실패 — 상위에서 세션 롤백 필요: %s", exc,
            )
            raise
        cache_map: Dict[Tuple, EventEnrichment] = {
            (r.ticker, r.event_date, r.event_type, r.detail_hash): r for r in cached
        }

        miss_events: List[TimelineEvent] = []
        miss_indices: List[int] = []
        cache_hit = 0
        for idx, event in enumerate(targets):
            key = keys[idx]
            hit = cache_map.get(key)
            if hit and hit.importance_score is not None:
                event.importance_score = hit.importance_score
                cache_hit += 1
            else:
                miss_events.append(event)
                miss_indices.append(idx)

        if not miss_events:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "[MacroImportance] 전체 캐시 적중: %d건 (elapsed=%dms)",
                cache_hit, elapsed_ms,
                extra={
                    "llm_op": "macro_importance",
                    "cache_hit": cache_hit,
                    "llm_calls": 0,
                    "total": len(targets),
                    "elapsed_ms": elapsed_ms,
                },
            )
            return

        llm = get_workflow_llm(model=TITLE_MODEL)
        sem = asyncio.Semaphore(_CONCURRENCY)
        tasks = [
            _score_batch(llm, miss_events[i: i + _BATCH_SIZE], sem)
            for i in range(0, len(miss_events), _BATCH_SIZE)
        ]
        batch_results = await asyncio.gather(*tasks)
        flat_scores: List[float] = []
        for batch in batch_results:
            flat_scores.extend(batch)

        new_rows: List[EventEnrichment] = []
        for idx_in_miss, score in enumerate(flat_scores):
            original_idx = miss_indices[idx_in_miss]
            event = targets[original_idx]
            event.importance_score = score
            ticker, event_date, event_type, detail_hash = keys[original_idx]
            new_rows.append(
                EventEnrichment(
                    ticker=ticker,
                    event_date=event_date,
                    event_type=event_type,
                    detail_hash=detail_hash,
                    title=event.title or event.type,
                    importance_score=score,
                )
            )

        if new_rows:
            try:
                await self._repo.upsert_bulk(new_rows)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[MacroImportance] 점수 저장 실패 (무시): %s", exc)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "[MacroImportance] 완료: cache_hit=%d, llm=%d, total=%d, elapsed=%dms",
            cache_hit, len(miss_events), len(targets), elapsed_ms,
            extra={
                "llm_op": "macro_importance",
                "cache_hit": cache_hit,
                "llm_calls": len(miss_events),
                "total": len(targets),
                "batches": len(batch_results),
                "elapsed_ms": elapsed_ms,
            },
        )
