"""/macro-timeline 엔드포인트 스모크 테스트."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.common.exception.global_exception_handler import register_exception_handlers
from app.domains.history_agent.adapter.inbound.api.history_agent_router import router
from app.domains.history_agent.application.response.timeline_response import TimelineEvent
from app.domains.history_agent.di import get_collect_important_macro_events_usecase
from app.infrastructure.cache.redis_client import get_redis

pytestmark = pytest.mark.asyncio


def _fake_event(title: str, score: float, date: datetime.date) -> TimelineEvent:
    return TimelineEvent(
        title=title,
        date=date,
        category="MACRO",
        type="CRISIS",
        detail=f"detail-{title}",
        source="curated:US",
        importance_score=score,
    )


@pytest.fixture
def app_with_mocks():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    register_exception_handlers(app)

    uc = MagicMock()
    uc.execute = AsyncMock(
        return_value=[
            _fake_event("Fed 제로금리", 1.0, datetime.date(2020, 3, 15)),
            _fake_event("SVB 파산", 0.95, datetime.date(2023, 3, 10)),
        ]
    )

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)

    app.dependency_overrides[get_collect_important_macro_events_usecase] = lambda: uc
    app.dependency_overrides[get_redis] = lambda: redis
    return app, uc, redis


async def test_macro_timeline_returns_sorted_events(app_with_mocks):
    app, uc, redis = app_with_mocks
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/history-agent/macro-timeline",
            params={"period": "5Y", "region": "US", "limit": 10},
        )
    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["count"] == 2
    assert data["region"] == "US"
    assert data["ticker"] is None
    assert data["asset_type"] == "MACRO"
    assert [e["title"] for e in data["events"]] == ["Fed 제로금리", "SVB 파산"]
    uc.execute.assert_awaited_once_with(region="US", period="5Y", top_n=10)
    redis.setex.assert_awaited_once()


async def test_macro_timeline_invalid_region_returns_400(app_with_mocks):
    app, *_ = app_with_mocks
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/history-agent/macro-timeline",
            params={"region": "JP"},
        )
    assert response.status_code == 400


async def test_macro_timeline_cache_hit_skips_usecase(app_with_mocks):
    app, uc, redis = app_with_mocks
    cached_payload = (
        '{"ticker":null,"period":"1Y","count":1,"events":[{"title":"cached",'
        '"date":"2024-01-01","category":"MACRO","type":"CRISIS","detail":"x",'
        '"importance_score":1.0}],"is_etf":false,"asset_type":"MACRO","region":"US"}'
    )
    redis.get = AsyncMock(return_value=cached_payload)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/history-agent/macro-timeline",
            params={"period": "1Y", "region": "US"},
        )
    assert response.status_code == 200
    uc.execute.assert_not_awaited()
    data = response.json()["data"]
    assert data["events"][0]["title"] == "cached"
