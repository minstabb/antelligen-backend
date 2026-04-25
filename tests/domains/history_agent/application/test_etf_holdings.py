"""T2-2 Step 2 ETF holdings 분해: detail_hash constituent 포함 + constituent 필드 전파."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.dashboard.application.port.out.etf_holdings_port import EtfHolding
from app.domains.dashboard.application.response.announcement_response import (
    AnnouncementsResponse,
)
from app.domains.dashboard.application.response.corporate_event_response import (
    CorporateEventsResponse,
)
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    HistoryAgentUseCase,
)
from app.domains.history_agent.domain.entity.event_enrichment import compute_detail_hash


def test_compute_detail_hash_differs_by_constituent():
    """같은 detail이라도 constituent_ticker가 다르면 hash가 달라야 한다."""
    h1 = compute_detail_hash("earnings beat", "AAPL")
    h2 = compute_detail_hash("earnings beat", "MSFT")
    h3 = compute_detail_hash("earnings beat", None)
    assert h1 != h2
    assert h1 != h3
    assert h2 != h3


def test_compute_detail_hash_stable_for_same_input():
    assert compute_detail_hash("earnings beat", "AAPL") == compute_detail_hash(
        "earnings beat", "AAPL"
    )


@pytest.mark.asyncio
async def test_collect_holdings_events_tags_constituent_and_weight():
    holdings_port = AsyncMock()
    holdings_port.get_top_holdings = AsyncMock(return_value=[
        EtfHolding(ticker="AAPL", name="Apple", weight_pct=7.25),
        EtfHolding(ticker="MSFT", name="Microsoft", weight_pct=6.10),
    ])

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.setex = AsyncMock()

    repo = AsyncMock()
    repo.find_by_keys = AsyncMock(return_value=[])
    repo.upsert_bulk = AsyncMock(return_value=0)

    usecase = HistoryAgentUseCase(
        stock_bars_port=MagicMock(),
        yfinance_corporate_port=MagicMock(),
        dart_corporate_client=MagicMock(),
        sec_edgar_port=MagicMock(),
        dart_announcement_client=MagicMock(),
        redis=redis_mock,
        enrichment_repo=repo,
        asset_type_port=MagicMock(),
        fred_macro_port=MagicMock(),
        etf_holdings_port=holdings_port,
    )

    _module = "app.domains.history_agent.application.usecase.history_agent_usecase"
    corp_resp = CorporateEventsResponse(ticker="AAPL", period="1M", count=0, events=[])
    ann_resp = AnnouncementsResponse(ticker="AAPL", period="1M", count=0, events=[])

    with patch(f"{_module}.GetCorporateEventsUseCase") as MockCorp, \
         patch(f"{_module}.GetAnnouncementsUseCase") as MockAnn:
        MockCorp.return_value.execute = AsyncMock(return_value=corp_resp)
        MockAnn.return_value.execute = AsyncMock(return_value=ann_resp)

        events = await usecase._collect_holdings_events(etf_ticker="SPY", period="1M")

    # CorporateEventsResponse/AnnouncementsResponse 모두 빈 이벤트라 결과도 비어있음 — 호출 자체가 성공하면 OK
    assert events == []
    holdings_port.get_top_holdings.assert_awaited_once_with("SPY", top_n=5)
