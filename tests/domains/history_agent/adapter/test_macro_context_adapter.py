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


# §13.4 B perf — top_k cap 검증
@pytest.mark.asyncio
async def test_related_assets_top_k_caps_largest_abs_changes():
    # threshold 통과 후보 5개 — 변화율 -3, +5, -10, +2.55, +7
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {
                "symbol": "^VIX",
                "name": "VIX",
                "bars": [
                    {"date": "2026-01-01", "close": 10.0},
                    {"date": "2026-01-02", "close": 9.7},      # -3.0%
                    {"date": "2026-01-03", "close": 10.185},   # +5.0%
                    {"date": "2026-01-04", "close": 9.1665},   # -10.0%
                    {"date": "2026-01-05", "close": 9.4},      # +2.55%
                    {"date": "2026-01-06", "close": 10.058},   # +7.0%
                ],
            }
        ]
    )
    adapter = RelatedAssetsAdapter(client=client)
    events = await adapter.fetch_significant_moves(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        threshold_pct=2.0,
        top_k=3,
    )
    # |Δ%| 큰 순: -10, +7, +5  → 3건
    assert len(events) == 3
    abs_changes = sorted([abs(e.change_pct or 0) for e in events], reverse=True)
    assert abs_changes == pytest.approx([10.0, 7.0, 5.0], abs=0.05)


@pytest.mark.asyncio
async def test_related_assets_no_top_k_returns_all():
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {
                "symbol": "^VIX",
                "name": "VIX",
                "bars": [
                    {"date": "2026-01-01", "close": 10.0},
                    {"date": "2026-01-02", "close": 9.7},     # -3.0%
                    {"date": "2026-01-03", "close": 10.185},  # +5.0%
                    {"date": "2026-01-04", "close": 9.1665},  # -10.0%
                ],
            }
        ]
    )
    adapter = RelatedAssetsAdapter(client=client)
    events = await adapter.fetch_significant_moves(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        threshold_pct=2.0,
        # top_k 미전달 — backward compat
    )
    assert len(events) == 3


@pytest.mark.asyncio
async def test_gpr_top_k_caps_largest_changes():
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {"date": "2026-01-01", "gpr": 100.0},
            {"date": "2026-02-01", "gpr": 130.0},   # +30%
            {"date": "2026-03-01", "gpr": 195.0},   # +50%
            {"date": "2026-04-01", "gpr": 234.0},   # +20%
            {"date": "2026-05-01", "gpr": 327.6},   # +40%
        ]
    )
    adapter = GprIndexAdapter(client=client)
    events = await adapter.fetch_mom_spikes(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 5, 31),
        mom_change_pct=20.0,
        top_k=2,
    )
    # 4건 후보 (+30, +50, +20, +40) 중 큰 순 2개: +50, +40
    assert len(events) == 2
    changes = sorted([e.change_pct or 0 for e in events], reverse=True)
    assert changes[0] == pytest.approx(50.0, abs=0.1)
    assert changes[1] == pytest.approx(40.0, abs=0.1)


@pytest.mark.asyncio
async def test_gpr_no_top_k_returns_all():
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value=[
            {"date": "2026-01-01", "gpr": 100.0},
            {"date": "2026-02-01", "gpr": 130.0},   # +30%
            {"date": "2026-03-01", "gpr": 195.0},   # +50%
        ]
    )
    adapter = GprIndexAdapter(client=client)
    events = await adapter.fetch_mom_spikes(
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 3, 31),
        mom_change_pct=20.0,
    )
    assert len(events) == 2
