"""yfinance ticker → DART corp_code 매핑.

OKR 1 P1.5 — 한국 공시(DART) 통합용. yfinance 의 ticker 접미사(`.KS`/`.KQ`)
를 떼고 DART 의 `corp_code`(8자리) 로 변환. 매핑 테이블은 DART corpCode.xml
(전체 ~3000건) 을 lazy load 후 Redis 30일 cache.

호출자(causality_agent) 가 region.is_korea() 일 때만 호출. 미국 ticker(영문)
는 normalize 단계에서 None 반환.
"""
import json
import logging
from typing import Dict, Optional

import redis.asyncio as aioredis

from app.domains.disclosure.adapter.outbound.external.dart_corp_code_client import (
    DartCorpCodeClient,
)

logger = logging.getLogger(__name__)

_CACHE_KEY = "corp_code_map:v1"
_CACHE_TTL_SEC = 60 * 60 * 24 * 30  # 30일 — DART corpCode 갱신 주기보다 짧게


def _normalize_ticker(ticker: str) -> str:
    """yfinance ticker 에서 DART stock_code(6자리) 추출.

    "005930.KS" → "005930", "005930" → "005930", "AAPL" → "AAPL" (호출자가 거름).
    """
    upper = (ticker or "").upper().strip()
    return upper.split(".")[0]


async def ticker_to_corp_code(
    ticker: str,
    redis_client: Optional[aioredis.Redis] = None,
) -> Optional[str]:
    """yfinance ticker → DART corp_code(8자리). 매핑 없으면 None.

    호출 예: `await ticker_to_corp_code("005930.KS", redis)` → "00126380"
    """
    stock_code = _normalize_ticker(ticker)
    if not stock_code or not stock_code.isdigit() or len(stock_code) != 6:
        return None

    mapping = await _load_mapping(redis_client)
    return mapping.get(stock_code)


async def _load_mapping(redis_client: Optional[aioredis.Redis]) -> Dict[str, str]:
    """전체 stock_code → corp_code 매핑. Redis cache 우선, miss 시 DART fresh fetch.

    fresh fetch 는 ~3000건 corpCode.xml 다운로드 + 파싱(~5초). 이후 30일간 cache hit.
    """
    if redis_client is not None:
        try:
            cached = await redis_client.get(_CACHE_KEY)
            if cached is not None:
                payload = cached.decode() if isinstance(cached, (bytes, bytearray)) else cached
                return json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[corp_code_mapper] cache get 실패 — fresh fetch: %s", exc)

    try:
        client = DartCorpCodeClient()
        corps = await client.fetch_all_corp_codes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[corp_code_mapper] DART corpCode.xml 다운로드 실패: %s", exc)
        return {}

    mapping = {c.stock_code: c.corp_code for c in corps if c.stock_code}
    logger.info("[corp_code_mapper] 매핑 %d건 fresh fetch 완료", len(mapping))

    if redis_client is not None:
        try:
            await redis_client.setex(
                _CACHE_KEY,
                _CACHE_TTL_SEC,
                json.dumps(mapping, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[corp_code_mapper] cache set 실패 (graceful): %s", exc)

    return mapping
