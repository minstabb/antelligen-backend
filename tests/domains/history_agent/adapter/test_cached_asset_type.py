"""CachedAssetTypeAdapter — L1/L2 캐시 동작 + miss 시 underlying 호출."""

from unittest.mock import AsyncMock

import pytest

from app.domains.dashboard.adapter.outbound.external.cached_asset_type_adapter import (
    CachedAssetTypeAdapter,
)


class _StubInner:
    def __init__(self, value: str):
        self.value = value
        self.calls = 0

    async def get_quote_type(self, ticker: str) -> str:
        self.calls += 1
        return self.value


@pytest.mark.asyncio
async def test_redis_hit_returns_cached_value():
    inner = _StubInner("EQUITY")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="ETF")
    redis.setex = AsyncMock()

    adapter = CachedAssetTypeAdapter(inner, redis)
    result = await adapter.get_quote_type("SPY")

    assert result == "ETF"
    inner.calls == 0  # underlying 미호출
    redis.setex.assert_not_called()


@pytest.mark.asyncio
async def test_miss_hits_underlying_and_writes_redis():
    inner = _StubInner("ETF")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    adapter = CachedAssetTypeAdapter(inner, redis)
    result = await adapter.get_quote_type("SPY")

    assert result == "ETF"
    assert inner.calls == 1
    redis.setex.assert_called_once()
    args = redis.setex.call_args.args
    assert args[0] == "asset_type:SPY"
    assert args[2] == "ETF"


@pytest.mark.asyncio
async def test_l1_cache_blocks_second_call():
    inner = _StubInner("EQUITY")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    adapter = CachedAssetTypeAdapter(inner, redis)
    await adapter.get_quote_type("AAPL")
    await adapter.get_quote_type("AAPL")  # 두번째 호출은 L1에서 반환

    assert inner.calls == 1
    assert redis.get.call_count == 1


@pytest.mark.asyncio
async def test_unknown_not_cached_in_redis():
    """UNKNOWN 은 오분류 가능성이 있으므로 Redis에 장기 캐시하지 않는다."""
    inner = _StubInner("UNKNOWN")
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    adapter = CachedAssetTypeAdapter(inner, redis)
    result = await adapter.get_quote_type("ZZZ")

    assert result == "UNKNOWN"
    redis.setex.assert_not_called()


@pytest.mark.asyncio
async def test_redis_none_does_not_crash():
    """redis=None 이어도 동작해야 — 로컬 캐시만 쓰는 경로."""
    inner = _StubInner("EQUITY")
    adapter = CachedAssetTypeAdapter(inner, None)
    result = await adapter.get_quote_type("AAPL")
    assert result == "EQUITY"
    assert inner.calls == 1
