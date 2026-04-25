"""CuratedMacroEventsAdapter — JSON 시드 로딩과 region·날짜 필터링."""

import datetime
import json
from pathlib import Path

import pytest

from app.domains.history_agent.adapter.outbound.curated_macro_events_adapter import (
    CuratedMacroEventsAdapter,
    _load_catalog,
)


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    data = [
        {
            "date": "2020-03-15",
            "event_type": "POLICY",
            "region": "US",
            "title": "Fed 제로금리",
            "detail": "긴급 인하",
            "tags": ["policy"],
            "importance_score": 1.0,
        },
        {
            "date": "2022-02-24",
            "event_type": "GEOPOLITICAL",
            "region": "GLOBAL",
            "title": "러시아 우크라이나 침공",
            "detail": "전면 침공",
            "tags": ["war"],
            "importance_score": 1.0,
        },
        {
            "date": "2022-09-28",
            "event_type": "CRISIS",
            "region": "KR",
            "title": "레고랜드 ABCP",
            "detail": "신용경색",
            "tags": ["credit"],
            "importance_score": 0.85,
        },
    ]
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    _load_catalog.cache_clear()
    return path


@pytest.mark.asyncio
async def test_fetch_filters_by_region_includes_global(seed_file: Path):
    adapter = CuratedMacroEventsAdapter(seed_path=seed_file)
    events = await adapter.fetch(
        region="US",
        start_date=datetime.date(2019, 1, 1),
        end_date=datetime.date(2023, 1, 1),
    )
    # US + GLOBAL 합쳐 2건, KR 제외
    assert {e.region for e in events} == {"US", "GLOBAL"}
    assert len(events) == 2


@pytest.mark.asyncio
async def test_fetch_region_global_returns_all_in_range(seed_file: Path):
    adapter = CuratedMacroEventsAdapter(seed_path=seed_file)
    events = await adapter.fetch(
        region="GLOBAL",
        start_date=datetime.date(2019, 1, 1),
        end_date=datetime.date(2023, 12, 31),
    )
    assert len(events) == 3


@pytest.mark.asyncio
async def test_fetch_date_range_excludes_out_of_window(seed_file: Path):
    adapter = CuratedMacroEventsAdapter(seed_path=seed_file)
    events = await adapter.fetch(
        region="GLOBAL",
        start_date=datetime.date(2021, 1, 1),
        end_date=datetime.date(2023, 1, 1),
    )
    # 2020-03 이벤트는 제외, 2022-02, 2022-09 두 건만
    dates = sorted(e.date for e in events)
    assert dates == [datetime.date(2022, 2, 24), datetime.date(2022, 9, 28)]


@pytest.mark.asyncio
async def test_fetch_missing_seed_returns_empty(tmp_path: Path):
    _load_catalog.cache_clear()
    missing = tmp_path / "does_not_exist.json"
    adapter = CuratedMacroEventsAdapter(seed_path=missing)
    events = await adapter.fetch(
        region="US",
        start_date=datetime.date(2020, 1, 1),
        end_date=datetime.date(2025, 1, 1),
    )
    assert events == []


@pytest.mark.asyncio
async def test_fetch_without_dates_returns_full_catalog(seed_file: Path):
    """S2-2: start/end_date 미지정 시 전체 카탈로그 반환 (과거 이벤트 포함)."""
    adapter = CuratedMacroEventsAdapter(seed_path=seed_file)
    events = await adapter.fetch(region="GLOBAL")
    assert len(events) == 3


@pytest.mark.asyncio
async def test_fetch_only_start_date(seed_file: Path):
    adapter = CuratedMacroEventsAdapter(seed_path=seed_file)
    events = await adapter.fetch(region="GLOBAL", start_date=datetime.date(2022, 1, 1))
    # 2020-03 제외, 2022 이벤트 2건 남음
    assert {e.date for e in events} == {datetime.date(2022, 2, 24), datetime.date(2022, 9, 28)}


@pytest.mark.asyncio
async def test_fetch_only_end_date(seed_file: Path):
    adapter = CuratedMacroEventsAdapter(seed_path=seed_file)
    events = await adapter.fetch(region="GLOBAL", end_date=datetime.date(2021, 12, 31))
    # 2022 이벤트 제외, 2020-03만 남음
    assert [e.date for e in events] == [datetime.date(2020, 3, 15)]
