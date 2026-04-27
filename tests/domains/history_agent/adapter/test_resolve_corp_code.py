"""`/timeline` router 의 `_resolve_corp_code` — yfinance suffix 처리 + DB/DART fallback (OKR 1 P1.5).

bug: 기존 코드가 normalize_yfinance_ticker 후 ".KS" 붙은 ticker 를
isdigit() 으로 검증해서 한국 종목 corp_code 가 항상 None 이었음.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.history_agent.adapter.inbound.api.history_agent_router import (
    _resolve_corp_code,
)


@pytest.mark.asyncio
async def test_resolves_via_db_when_company_exists():
    """DB Company 테이블 hit 시 그 corp_code 사용 + DART fallback 호출 안 함."""
    db = MagicMock()

    company_mock = MagicMock(corp_code="00126380")
    repo_mock = MagicMock()
    repo_mock.find_by_stock_code = AsyncMock(return_value=company_mock)

    with patch(
        "app.domains.disclosure.adapter.outbound.persistence.company_repository_impl.CompanyRepositoryImpl",
        return_value=repo_mock,
    ), patch(
        "app.infrastructure.external.corp_code_mapper.ticker_to_corp_code",
    ) as fallback_mock:
        result = await _resolve_corp_code("005930.KS", db)

    assert result == "00126380"
    repo_mock.find_by_stock_code.assert_awaited_once_with("005930")
    fallback_mock.assert_not_called()


@pytest.mark.asyncio
async def test_strips_kq_suffix_for_kosdaq():
    """`.KQ` (KOSDAQ) suffix 도 동일하게 떼고 stock_code 추출."""
    db = MagicMock()
    repo_mock = MagicMock()
    repo_mock.find_by_stock_code = AsyncMock(return_value=MagicMock(corp_code="00164779"))

    with patch(
        "app.domains.disclosure.adapter.outbound.persistence.company_repository_impl.CompanyRepositoryImpl",
        return_value=repo_mock,
    ):
        result = await _resolve_corp_code("068270.KQ", db)

    assert result == "00164779"
    repo_mock.find_by_stock_code.assert_awaited_once_with("068270")


@pytest.mark.asyncio
async def test_falls_back_to_dart_mapper_when_db_miss():
    """DB 에 없는 종목은 DART corpCode.xml mapper 로 fallback."""
    db = MagicMock()
    repo_mock = MagicMock()
    repo_mock.find_by_stock_code = AsyncMock(return_value=None)

    with patch(
        "app.domains.disclosure.adapter.outbound.persistence.company_repository_impl.CompanyRepositoryImpl",
        return_value=repo_mock,
    ), patch(
        "app.infrastructure.external.corp_code_mapper.ticker_to_corp_code",
        AsyncMock(return_value="00399025"),
    ) as fallback_mock:
        result = await _resolve_corp_code("373220.KS", db)

    assert result == "00399025"
    fallback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_returns_none_for_us_ticker():
    """미국 ticker (영문) → DB 조회 안 함, None."""
    db = MagicMock()
    with patch(
        "app.domains.disclosure.adapter.outbound.persistence.company_repository_impl.CompanyRepositoryImpl",
    ) as repo_class_mock:
        result = await _resolve_corp_code("AAPL", db)

    assert result is None
    repo_class_mock.assert_not_called()


@pytest.mark.asyncio
async def test_returns_none_for_index_ticker():
    """`^IXIC` 같은 INDEX ticker → None."""
    db = MagicMock()
    result = await _resolve_corp_code("^IXIC", db)
    assert result is None


@pytest.mark.asyncio
async def test_handles_raw_six_digit_ticker_without_suffix():
    """suffix 없는 raw `005930` 입력도 정상 처리 (router 정규화 전 경로 호환)."""
    db = MagicMock()
    repo_mock = MagicMock()
    repo_mock.find_by_stock_code = AsyncMock(return_value=MagicMock(corp_code="00126380"))

    with patch(
        "app.domains.disclosure.adapter.outbound.persistence.company_repository_impl.CompanyRepositoryImpl",
        return_value=repo_mock,
    ):
        result = await _resolve_corp_code("005930", db)

    assert result == "00126380"
    repo_mock.find_by_stock_code.assert_awaited_once_with("005930")
