import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.domains.company_profile.application.port.out.business_overview_cache_port import (
    BusinessOverviewCachePort,
)
from app.domains.company_profile.domain.value_object.business_overview import BusinessOverview

logger = logging.getLogger(__name__)


class RedisBusinessOverviewCache(BusinessOverviewCachePort):
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    @staticmethod
    def _key(corp_code: str) -> str:
        return f"company_overview:{corp_code}"

    async def get(self, corp_code: str) -> Optional[BusinessOverview]:
        try:
            raw = await self._redis.get(self._key(corp_code))
            if raw is None:
                return None
            payload = json.loads(raw)
            return BusinessOverview(
                summary=payload["summary"],
                revenue_sources=payload.get("revenue_sources", []),
                source=payload.get("source", "llm_only"),
            )
        except (aioredis.RedisError, json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("[BusinessOverview] 캐시 조회 실패 corp_code=%s: %s", corp_code, e)
            return None

    async def save(self, corp_code: str, overview: BusinessOverview, ttl_seconds: int) -> None:
        try:
            payload = {
                "summary": overview.summary,
                "revenue_sources": list(overview.revenue_sources),
                "source": overview.source,
            }
            await self._redis.setex(
                self._key(corp_code),
                ttl_seconds,
                json.dumps(payload, ensure_ascii=False),
            )
        except (aioredis.RedisError, TypeError) as e:
            logger.error("[BusinessOverview] 캐시 저장 실패 corp_code=%s: %s", corp_code, e)
