"""T1-4 asset_type 분기 + 캐시 키 포함 테스트."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.history_agent.application.usecase.history_agent_usecase import (
    HistoryAgentUseCase,
)


def _make_usecase_with_quote_type(quote_type: str, redis_get_return=None):
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=redis_get_return)
    redis_mock.setex = AsyncMock()

    asset_type_mock = AsyncMock()
    asset_type_mock.get_quote_type = AsyncMock(return_value=quote_type)

    repo = AsyncMock()
    repo.find_by_keys = AsyncMock(return_value=[])
    repo.upsert_bulk = AsyncMock(return_value=0)

    return HistoryAgentUseCase(
        stock_bars_port=MagicMock(),
        yfinance_corporate_port=MagicMock(),
        dart_corporate_client=MagicMock(),
        sec_edgar_port=MagicMock(),
        dart_announcement_client=MagicMock(),
        redis=redis_mock,
        enrichment_repo=repo,
        asset_type_port=asset_type_mock,
        fred_macro_port=MagicMock(),
    ), redis_mock


def test_build_cache_key_includes_asset_type_and_version():
    assert HistoryAgentUseCase._build_cache_key("EQUITY", "AAPL", "1Y", True) == (
        "history_agent:v3:EQUITY:AAPL:1Y"
    )
    assert HistoryAgentUseCase._build_cache_key("INDEX", "^IXIC", "1M", False) == (
        "history_agent:v3:INDEX:^IXIC:1M:no-titles"
    )


@pytest.mark.asyncio
async def test_unsupported_asset_type_returns_empty_response():
    """MUTUALFUND 같은 미지원 타입은 빈 타임라인 + asset_type=원본값 반환."""
    usecase, redis_mock = _make_usecase_with_quote_type("MUTUALFUND")

    result = await usecase.execute(ticker="VFIAX", period="1Y")

    assert result.count == 0
    assert result.events == []
    assert result.asset_type == "MUTUALFUND"
    redis_mock.setex.assert_called_once()
    cache_key = redis_mock.setex.call_args.args[0]
    assert "MUTUALFUND" in cache_key


@pytest.mark.asyncio
async def test_etf_dispatches_to_etf_path_without_causality():
    """ETF는 MACRO+뉴스 경로로 수집되며 is_etf=True. §13.4 C: PRICE 카테고리 제거됨."""
    usecase, redis_mock = _make_usecase_with_quote_type("ETF")

    _module = "app.domains.history_agent.application.usecase.history_agent_usecase"
    with patch(f"{_module}.GetEconomicEventsUseCase") as MockMacro, \
         patch(f"{_module}.enrich_macro_titles", new_callable=AsyncMock), \
         patch(f"{_module}.enrich_other_titles", new_callable=AsyncMock), \
         patch(f"{_module}._enrich_announcement_details", new_callable=AsyncMock):

        from app.domains.dashboard.application.response.economic_event_response import (
            EconomicEventsResponse,
        )
        MockMacro.return_value.execute = AsyncMock(
            return_value=EconomicEventsResponse(period="1Y", count=0, events=[])
        )

        result = await usecase.execute(ticker="SPY", period="1Y")

    assert result.is_etf is True
    assert result.asset_type == "ETF"


@pytest.mark.asyncio
async def test_asset_type_cache_key_present_in_redis():
    """캐시 키는 asset_type을 포함해야 한다(재분류 시 stale 방지)."""
    usecase, redis_mock = _make_usecase_with_quote_type("MUTUALFUND")
    await usecase.execute(ticker="VFIAX", period="1M")

    # redis.get 호출 키가 asset_type을 포함
    get_key = redis_mock.get.call_args.args[0]
    assert "MUTUALFUND" in get_key
    assert "history_agent:v3" in get_key
