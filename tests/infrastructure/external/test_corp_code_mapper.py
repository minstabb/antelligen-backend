"""ticker → corp_code 매핑 + Redis cache 동작 검증 (OKR 1 P1.5)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.disclosure.application.port.dart_corp_code_port import DartCorpInfo
from app.infrastructure.external.corp_code_mapper import (
    _normalize_ticker,
    ticker_to_corp_code,
)


# ── normalize ────────────────────────────────────────────────


def test_normalize_strips_yfinance_suffix():
    assert _normalize_ticker("005930.KS") == "005930"
    assert _normalize_ticker("068270.KQ") == "068270"
    assert _normalize_ticker("005930") == "005930"


def test_normalize_uppercases_and_handles_empty():
    assert _normalize_ticker("aapl") == "AAPL"
    assert _normalize_ticker("") == ""
    assert _normalize_ticker("  005930.ks  ") == "005930"


# ── invalid ticker → None (DART fetch 안 함) ─────────────────


@pytest.mark.asyncio
async def test_returns_none_for_non_korean_ticker():
    """미국 ticker 는 normalize 통과해도 6자리 숫자 검증에서 None."""
    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
    ) as client_mock:
        result = await ticker_to_corp_code("AAPL", redis_client=None)
    assert result is None
    client_mock.assert_not_called()


@pytest.mark.asyncio
async def test_returns_none_for_short_numeric_ticker():
    """3자리 숫자 등은 stock_code 형식 부적합 → None."""
    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
    ) as client_mock:
        result = await ticker_to_corp_code("123", redis_client=None)
    assert result is None
    client_mock.assert_not_called()


# ── fresh fetch (Redis 없음) ─────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_fetch_returns_corp_code():
    """Redis 없이도 DART 직접 호출해서 매핑 반환."""
    fake_corps = [
        DartCorpInfo(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
        DartCorpInfo(corp_code="00164779", corp_name="셀트리온", stock_code="068270", modify_date="20240101"),
    ]
    client_mock = MagicMock()
    client_mock.fetch_all_corp_codes = AsyncMock(return_value=fake_corps)

    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
        return_value=client_mock,
    ):
        result = await ticker_to_corp_code("005930.KS", redis_client=None)

    assert result == "00126380"
    client_mock.fetch_all_corp_codes.assert_awaited_once()


@pytest.mark.asyncio
async def test_fresh_fetch_returns_none_when_unmapped():
    """매핑 테이블에 없는 종목 → None."""
    fake_corps = [
        DartCorpInfo(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
    ]
    client_mock = MagicMock()
    client_mock.fetch_all_corp_codes = AsyncMock(return_value=fake_corps)

    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
        return_value=client_mock,
    ):
        result = await ticker_to_corp_code("999999.KS", redis_client=None)

    assert result is None


@pytest.mark.asyncio
async def test_dart_fetch_failure_returns_none_gracefully():
    """DART API 실패 시 raise 하지 말고 None 반환 (timeline 전체가 죽으면 안 됨)."""
    client_mock = MagicMock()
    client_mock.fetch_all_corp_codes = AsyncMock(side_effect=RuntimeError("DART down"))

    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
        return_value=client_mock,
    ):
        result = await ticker_to_corp_code("005930.KS", redis_client=None)

    assert result is None


# ── Redis cache 동작 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_cache_hit_skips_dart_fetch():
    """Redis 에 매핑이 있으면 DART API 호출 안 함."""
    cached_mapping = {"005930": "00126380"}
    redis_mock = MagicMock()
    redis_mock.get = AsyncMock(return_value=json.dumps(cached_mapping).encode("utf-8"))

    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
    ) as client_mock:
        result = await ticker_to_corp_code("005930.KS", redis_client=redis_mock)

    assert result == "00126380"
    client_mock.assert_not_called()
    redis_mock.get.assert_awaited_once_with("corp_code_map:v1")


@pytest.mark.asyncio
async def test_redis_cache_miss_triggers_fetch_and_setex():
    """Redis miss 시 fresh fetch + setex 로 30일 TTL cache 저장."""
    redis_mock = MagicMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.setex = AsyncMock()

    fake_corps = [
        DartCorpInfo(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
    ]
    client_mock = MagicMock()
    client_mock.fetch_all_corp_codes = AsyncMock(return_value=fake_corps)

    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
        return_value=client_mock,
    ):
        result = await ticker_to_corp_code("005930.KS", redis_client=redis_mock)

    assert result == "00126380"
    client_mock.fetch_all_corp_codes.assert_awaited_once()
    redis_mock.setex.assert_awaited_once()
    args = redis_mock.setex.await_args.args
    assert args[0] == "corp_code_map:v1"
    assert args[1] == 60 * 60 * 24 * 30  # 30일 TTL
    assert json.loads(args[2]) == {"005930": "00126380"}


@pytest.mark.asyncio
async def test_redis_get_failure_falls_back_to_fresh_fetch():
    """Redis get 예외 → graceful fallback."""
    redis_mock = MagicMock()
    redis_mock.get = AsyncMock(side_effect=ConnectionError("redis down"))
    redis_mock.setex = AsyncMock()

    fake_corps = [
        DartCorpInfo(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
    ]
    client_mock = MagicMock()
    client_mock.fetch_all_corp_codes = AsyncMock(return_value=fake_corps)

    with patch(
        "app.infrastructure.external.corp_code_mapper.DartCorpCodeClient",
        return_value=client_mock,
    ):
        result = await ticker_to_corp_code("005930.KS", redis_client=redis_mock)

    assert result == "00126380"
