"""매크로 타임라인 응답을 미리 Redis에 채워 둬 cold 요청 180s 타임아웃을 방지한다.

품질 리포트 S1-2(2026-04-21) 대응. 9개 조합 `(region, period)`를
새벽 비업무 시간대에 한 번씩 조회해 `macro_timeline:v1:*` 키를 갱신한다.
실패한 조합은 로깅만 하고 다음 조합을 계속 진행한다.
"""
from __future__ import annotations

import logging

from app.domains.history_agent.adapter.outbound.curated_macro_events_adapter import (
    CuratedMacroEventsAdapter,
)
from app.domains.history_agent.adapter.outbound.macro_context_adapter import (
    GprIndexAdapter,
    RelatedAssetsAdapter,
)
from app.domains.history_agent.adapter.outbound.persistence.event_enrichment_repository_impl import (
    EventEnrichmentRepositoryImpl,
)
from app.domains.history_agent.application.response.timeline_response import TimelineResponse
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
)
from app.domains.dashboard.adapter.outbound.external.fred_macro_client import FredMacroClient
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_MACRO_CACHE_VERSION = "v1"

# 워밍업 대상: 모든 region × 사용자가 자주 요청하는 period
# cold에서 ≥60s 걸리는 조합 위주(1Y 이하는 cold도 1~2s라 제외해도 무방하지만 안정성 차원에서 포함)
_WARMUP_COMBOS: list[tuple[str, str]] = [
    ("US", "1Y"), ("US", "5Y"), ("US", "10Y"),
    ("KR", "1Y"), ("KR", "5Y"), ("KR", "10Y"),
    ("GLOBAL", "1Y"), ("GLOBAL", "5Y"), ("GLOBAL", "10Y"),
]


async def job_warmup_macro_timeline() -> None:
    """9개 (region, period) 조합 macro-timeline 응답을 미리 Redis에 채워 둔다."""
    settings = get_settings()
    top_n = settings.macro_timeline_top_n
    ttl = settings.macro_cache_ttl_seconds
    redis = get_redis()
    fred = FredMacroClient()
    related = RelatedAssetsAdapter()
    gpr = GprIndexAdapter()
    curated = CuratedMacroEventsAdapter()

    logger.info("[macro_warmup] 시작: combos=%d, top_n=%d", len(_WARMUP_COMBOS), top_n)
    success = 0
    for region, period in _WARMUP_COMBOS:
        async with AsyncSessionLocal() as session:
            repo = EventEnrichmentRepositoryImpl(session)
            usecase = CollectImportantMacroEventsUseCase(
                fred_macro_port=fred,
                curated_port=curated,
                related_assets_port=related,
                gpr_index_port=gpr,
                enrichment_repo=repo,
            )
            try:
                events = await usecase.execute(region=region, period=period, top_n=top_n)
                response = TimelineResponse(
                    ticker=None,
                    period=period,
                    count=len(events),
                    events=events,
                    region=region,
                    asset_type="MACRO",
                )
                cache_key = f"macro_timeline:{_MACRO_CACHE_VERSION}:{region}:{period}:{top_n}"
                await redis.setex(cache_key, ttl, response.model_dump_json())
                success += 1
                logger.info(
                    "[macro_warmup] ✓ region=%s period=%s events=%d → %s",
                    region, period, len(events), cache_key,
                )
            except Exception as exc:
                logger.warning(
                    "[macro_warmup] ✗ region=%s period=%s 실패: %s",
                    region, period, exc,
                )
    logger.info("[macro_warmup] 완료: %d/%d 성공", success, len(_WARMUP_COMBOS))
