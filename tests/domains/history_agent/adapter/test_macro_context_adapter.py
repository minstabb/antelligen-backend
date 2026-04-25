"""RelatedAssetsAdapter + GprIndexAdapter — threshold 기반 이벤트 승격."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.history_agent.adapter.outbound.macro_context_adapter import (
    GprIndexAdapter,
    RelatedAssetsAdapter,
)


@pytest.mark.asyncio
async def test_related_assets_promotes_only_large_moves():
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {
                "symbol": "^VIX",
                "name": "VIX",
                "bars": [
                    {"date": "2026-03-01", "close": 15.0},
                    {"date": "2026-03-02", "close": 15.1},  # +0.67% → skip
                    {"date": "2026-03-03", "close": 18.0},  # +19% → VIX_SPIKE
                ],
            },
            {
                "symbol": "CL=F",
                "name": "WTI",
                "bars": [
                    {"date": "2026-03-01", "close": 80.0},
                    {"date": "2026-03-02", "close": 80.5},  # +0.6% → skip
                ],
            },
        ]
    )
    adapter = RelatedAssetsAdapter(client=client)
    events = await adapter.fetch_significant_moves(
        start_date=datetime.date(2026, 3, 1),
        end_date=datetime.date(2026, 3, 31),
        threshold_pct=2.0,
    )

    assert len(events) == 1
    assert events[0].type == "VIX_SPIKE"
    assert events[0].change_pct is not None
    assert events[0].change_pct > 2


@pytest.mark.asyncio
async def test_related_assets_empty_when_client_returns_empty():
    client = MagicMock()
    client.fetch = AsyncMock(return_value=[])
    adapter = RelatedAssetsAdapter(client=client)
    events = await adapter.fetch_significant_moves(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        threshold_pct=2.0,
    )
    assert events == []


@pytest.mark.asyncio
async def test_gpr_mom_spike_detected():
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {"date": "2026-01-01", "gpr": 100.0},
            {"date": "2026-02-01", "gpr": 105.0},  # +5% MoM
            {"date": "2026-03-01", "gpr": 140.0},  # +33% MoM → spike
        ]
    )
    adapter = GprIndexAdapter(client=client)
    events = await adapter.fetch_mom_spikes(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 3, 31),
        mom_change_pct=20.0,
    )

    assert len(events) == 1
    assert events[0].type == "GEOPOLITICAL_RISK"
    assert events[0].change_pct is not None
    assert events[0].change_pct > 20


@pytest.mark.asyncio
async def test_gpr_returns_empty_when_no_spike():
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {"date": "2026-01-01", "gpr": 100.0},
            {"date": "2026-02-01", "gpr": 105.0},
        ]
    )
    adapter = GprIndexAdapter(client=client)
    events = await adapter.fetch_mom_spikes(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 2, 28),
        mom_change_pct=20.0,
    )
    assert events == []
