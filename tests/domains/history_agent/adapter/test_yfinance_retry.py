"""yfinance_call_with_retry — 429/transient 시 backoff, 도메인 예외는 즉시 전파."""

from unittest.mock import patch

import pytest

from app.domains.dashboard.adapter.outbound.external._yfinance_retry import (
    _is_rate_limit_exc,
    _is_retryable,
    yfinance_call_with_retry,
)


class _FakeRateLimit(Exception):
    pass


_FakeRateLimit.__name__ = "YFRateLimitError"


def test_is_rate_limit_detects_name():
    class YFRateLimitError(Exception):
        pass

    assert _is_rate_limit_exc(YFRateLimitError())


def test_is_rate_limit_detects_429_message():
    assert _is_rate_limit_exc(Exception("Got 429 Too Many Requests"))


def test_is_rate_limit_detects_429_response():
    err = Exception("boom")
    err.response = type("R", (), {"status_code": 429})()
    assert _is_rate_limit_exc(err)


def test_is_not_rate_limit_for_plain_error():
    assert not _is_rate_limit_exc(ValueError("invalid ticker"))


def test_is_retryable_includes_transient():
    class Timeout(Exception):
        pass
    assert _is_retryable(Timeout())


@pytest.mark.asyncio
async def test_retry_returns_success_without_sleep():
    call_count = {"n": 0}

    def fn():
        call_count["n"] += 1
        return "ok"

    with patch(
        "app.domains.dashboard.adapter.outbound.external._yfinance_retry.asyncio.sleep",
    ) as mock_sleep:
        result = await yfinance_call_with_retry(
            fn, logger_prefix="test", max_attempts=3, base_delay=0.01,
        )
    assert result == "ok"
    assert call_count["n"] == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_succeeds_after_one_rate_limit():
    class YFRateLimitError(Exception):
        pass

    call_count = {"n": 0}

    def fn():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise YFRateLimitError("too many")
        return "ok"

    with patch(
        "app.domains.dashboard.adapter.outbound.external._yfinance_retry.asyncio.sleep",
    ) as mock_sleep:
        result = await yfinance_call_with_retry(
            fn, logger_prefix="test", max_attempts=3, base_delay=0.01,
        )
    assert result == "ok"
    assert call_count["n"] == 2
    mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_retry_exhausts_and_reraises_on_persistent_rate_limit():
    class YFRateLimitError(Exception):
        pass

    def fn():
        raise YFRateLimitError("persistent 429")

    with patch(
        "app.domains.dashboard.adapter.outbound.external._yfinance_retry.asyncio.sleep",
    ):
        with pytest.raises(YFRateLimitError):
            await yfinance_call_with_retry(
                fn, logger_prefix="test", max_attempts=3, base_delay=0.01,
            )


@pytest.mark.asyncio
async def test_retry_propagates_domain_exception_immediately():
    """InvalidTicker 같은 비-transient 예외는 즉시 re-raise — 재시도 비용 없음."""
    call_count = {"n": 0}

    def fn():
        call_count["n"] += 1
        raise ValueError("invalid ticker: XYZ")

    with patch(
        "app.domains.dashboard.adapter.outbound.external._yfinance_retry.asyncio.sleep",
    ) as mock_sleep:
        with pytest.raises(ValueError):
            await yfinance_call_with_retry(
                fn, logger_prefix="test", max_attempts=5, base_delay=0.01,
            )
    assert call_count["n"] == 1  # 재시도 없음
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_backoff_delays_grow_exponentially():
    class YFRateLimitError(Exception):
        pass

    def fn():
        raise YFRateLimitError("429")

    delays = []

    async def fake_sleep(d):
        delays.append(d)

    with patch(
        "app.domains.dashboard.adapter.outbound.external._yfinance_retry.asyncio.sleep",
        side_effect=fake_sleep,
    ):
        with pytest.raises(YFRateLimitError):
            await yfinance_call_with_retry(
                fn, logger_prefix="test", max_attempts=4, base_delay=1.0,
            )
    # 실패 3번 + 마지막 raise → sleep 은 3회 전 2회만 실행 (마지막 시도 후엔 sleep 안 함)
    # 구현: for attempt in 1..4; 마지막에 raise → sleep 3회
    assert delays == [1.0, 2.0, 4.0]
