"""yfinance 호출용 공통 retry 래퍼.

429 rate-limit / 일시적 네트워크 오류에 한해 지수 백오프로 재시도한다.
도메인 예외(예: InvalidTickerException)나 빈 결과에는 개입하지 않는다.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional, TypeVar

from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RATE_LIMIT_EXC_NAMES = {"YFRateLimitError", "TooManyRequests"}
_TRANSIENT_EXC_NAMES = {
    "ConnectionError",
    "Timeout",
    "ReadTimeout",
    "ConnectTimeout",
    "RemoteDisconnected",
    "ProtocolError",
    "ChunkedEncodingError",
}


def _is_rate_limit_exc(exc: BaseException) -> bool:
    if type(exc).__name__ in _RATE_LIMIT_EXC_NAMES:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _is_transient_exc(exc: BaseException) -> bool:
    if type(exc).__name__ in _TRANSIENT_EXC_NAMES:
        return True
    try:
        import requests
        if isinstance(
            exc,
            (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ),
        ):
            return True
        if isinstance(exc, requests.exceptions.HTTPError):
            resp = getattr(exc, "response", None)
            if getattr(resp, "status_code", None) in {429, 500, 502, 503, 504}:
                return True
    except ImportError:
        pass
    return False


def _is_retryable(exc: BaseException) -> bool:
    return _is_rate_limit_exc(exc) or _is_transient_exc(exc)


async def yfinance_call_with_retry(
    fn: Callable[[], T],
    *,
    logger_prefix: str,
    max_attempts: Optional[int] = None,
    base_delay: Optional[float] = None,
) -> T:
    """blocking yfinance 호출을 executor에서 실행하며 rate-limit retry를 적용.

    - 429 / 연결·타임아웃 오류는 base_delay * 2^(n-1) 로 backoff 후 재시도.
    - 그 외 예외는 즉시 전파 (도메인 예외 보존).
    - 모든 시도 실패 시 마지막 예외를 re-raise — 호출자가 기존 방식대로 처리.
    """
    settings = get_settings()
    attempts = max_attempts or settings.yfinance_retry_max_attempts
    base = base_delay if base_delay is not None else settings.yfinance_retry_base_delay

    loop = asyncio.get_event_loop()
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            result = await loop.run_in_executor(None, fn)
            if attempt > 1:
                logger.info(
                    "[%s] yfinance_retry 성공: attempt=%d",
                    logger_prefix, attempt,
                )
            return result
        except BaseException as exc:  # noqa: BLE001
            if not _is_retryable(exc):
                raise
            last_exc = exc
            if attempt >= attempts:
                logger.warning(
                    "[%s] yfinance_retry 소진: attempts=%d, error=%s",
                    logger_prefix, attempt, exc,
                )
                raise
            delay = base * (2 ** (attempt - 1))
            logger.info(
                "[%s] yfinance_retry attempt=%d 대기 %.1fs: %s",
                logger_prefix, attempt, delay, exc,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


async def yfinance_async_call_with_retry(
    coro_fn: Callable[[], Awaitable[T]],
    *,
    logger_prefix: str,
    max_attempts: Optional[int] = None,
    base_delay: Optional[float] = None,
) -> T:
    """이미 async 인 함수를 retry로 감쌀 때 사용."""
    settings = get_settings()
    attempts = max_attempts or settings.yfinance_retry_max_attempts
    base = base_delay if base_delay is not None else settings.yfinance_retry_base_delay

    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_fn()
        except BaseException as exc:  # noqa: BLE001
            if not _is_retryable(exc):
                raise
            last_exc = exc
            if attempt >= attempts:
                logger.warning(
                    "[%s] yfinance_retry 소진: attempts=%d, error=%s",
                    logger_prefix, attempt, exc,
                )
                raise
            delay = base * (2 ** (attempt - 1))
            logger.info(
                "[%s] yfinance_retry attempt=%d 대기 %.1fs: %s",
                logger_prefix, attempt, delay, exc,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
