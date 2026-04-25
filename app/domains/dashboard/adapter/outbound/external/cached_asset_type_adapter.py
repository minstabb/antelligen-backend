"""asset_type 캐싱 어댑터.

asset_type은 상장 후 거의 바뀌지 않으므로 요청마다 yfinance를 치는 낭비를 제거한다.
L1 프로세스 로컬 dict + L2 Redis(24h) 2중 캐시. miss일 때만 underlying port 호출.
"""

import logging
from typing import Dict, Optional

import redis.asyncio as aioredis

from app.domains.dashboard.application.port.out.asset_type_port import AssetTypePort

logger = logging.getLogger(__name__)

_REDIS_TTL_SECONDS = 24 * 60 * 60  # 24h


class CachedAssetTypeAdapter(AssetTypePort):
    """AssetTypePort 를 감싸는 캐싱 데코레이터."""

    def __init__(self, inner: AssetTypePort, redis: Optional[aioredis.Redis]):
        self._inner = inner
        self._redis = redis
        self._local: Dict[str, str] = {}

    async def get_quote_type(self, ticker: str) -> str:
        key = ticker.upper()

        if key in self._local:
            return self._local[key]

        if self._redis is not None:
            try:
                cached = await self._redis.get(f"asset_type:{key}")
                if cached:
                    val = cached if isinstance(cached, str) else cached.decode()
                    self._local[key] = val
                    return val
            except Exception as exc:
                logger.warning("[CachedAssetType] redis get 실패 (ticker=%s): %s", ticker, exc)

        quote_type = await self._inner.get_quote_type(ticker)

        self._local[key] = quote_type
        if self._redis is not None and quote_type and quote_type != "UNKNOWN":
            try:
                await self._redis.setex(f"asset_type:{key}", _REDIS_TTL_SECONDS, quote_type)
            except Exception as exc:
                logger.warning("[CachedAssetType] redis setex 실패 (ticker=%s): %s", ticker, exc)
        return quote_type
