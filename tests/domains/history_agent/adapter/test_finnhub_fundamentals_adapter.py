"""FinnhubFundamentalsAdapter — 레이팅 비율 변동 + 실적 서프라이즈 → Fundamentals 이벤트."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.history_agent.adapter.outbound.finnhub_fundamentals_adapter import (
    FinnhubFundamentalsAdapter,
)


def _make_client(*, recommendations=None, earnings=None):
    client = MagicMock()
    client.get_recommendation_trend = AsyncMock(return_value=recommendations or [])
    client.get_earnings_surprise = AsyncMock(return_value=earnings or [])
    return client


@pytest.mark.asyncio
async def test_rating_upgrade_detected_when_buy_ratio_rises():
    today = datetime.date.today()
    last_month = (today - datetime.timedelta(days=30)).replace(day=1)
    this_month = today.replace(day=1)
    records = [
        {"period": last_month.isoformat(), "strongBuy": 0, "buy": 3, "hold": 5, "sell": 2, "strongSell": 0},
        {"period": this_month.isoformat(), "strongBuy": 5, "buy": 5, "hold": 0, "sell": 0, "strongSell": 0},
    ]
    client = _make_client(recommendations=records)
    adapter = FinnhubFundamentalsAdapter(client=client)

    events = await adapter.fetch_events(ticker="AAPL", period="3M")
    upgrades = [e for e in events if e.type == "ANALYST_UPGRADE"]

    assert len(upgrades) == 1
    assert upgrades[0].change_pct is not None
    assert upgrades[0].change_pct > 0


@pytest.mark.asyncio
async def test_rating_below_threshold_ignored():
    today = datetime.date.today()
    last_month = (today - datetime.timedelta(days=30)).replace(day=1)
    this_month = today.replace(day=1)
    # buy ratio 가 살짝만 움직이는 경우 (임계치 10%p 미만)
    records = [
        {"period": last_month.isoformat(), "strongBuy": 0, "buy": 5, "hold": 5, "sell": 0, "strongSell": 0},
        {"period": this_month.isoformat(), "strongBuy": 0, "buy": 6, "hold": 4, "sell": 0, "strongSell": 0},
    ]
    client = _make_client(recommendations=records)
    adapter = FinnhubFundamentalsAdapter(client=client)

    events = await adapter.fetch_events(ticker="AAPL", period="3M")
    assert all(e.type != "ANALYST_UPGRADE" for e in events)
    assert all(e.type != "ANALYST_DOWNGRADE" for e in events)


@pytest.mark.asyncio
async def test_earnings_beat_detected():
    today = datetime.date.today().replace(day=1)
    earnings = [
        {"period": today.isoformat(), "actual": 1.52, "estimate": 1.40, "surprisePercent": 8.5},
    ]
    client = _make_client(earnings=earnings)
    adapter = FinnhubFundamentalsAdapter(client=client)

    events = await adapter.fetch_events(ticker="AAPL", period="3M")
    beats = [e for e in events if e.type == "EARNINGS_BEAT"]
    assert len(beats) == 1
    assert beats[0].change_pct == 8.5


@pytest.mark.asyncio
async def test_earnings_small_surprise_ignored():
    today = datetime.date.today().replace(day=1)
    earnings = [
        {"period": today.isoformat(), "actual": 1.52, "estimate": 1.51, "surprisePercent": 0.6},
    ]
    client = _make_client(earnings=earnings)
    adapter = FinnhubFundamentalsAdapter(client=client)

    events = await adapter.fetch_events(ticker="AAPL", period="3M")
    assert events == []


@pytest.mark.asyncio
async def test_earnings_miss_detected_when_negative():
    today = datetime.date.today().replace(day=1)
    earnings = [
        {"period": today.isoformat(), "actual": 1.30, "estimate": 1.45, "surprisePercent": -10.3},
    ]
    client = _make_client(earnings=earnings)
    adapter = FinnhubFundamentalsAdapter(client=client)

    events = await adapter.fetch_events(ticker="AAPL", period="3M")
    misses = [e for e in events if e.type == "EARNINGS_MISS"]
    assert len(misses) == 1
    assert misses[0].change_pct == -10.3
