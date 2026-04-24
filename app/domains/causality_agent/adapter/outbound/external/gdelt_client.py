import asyncio
import logging
import time
from datetime import date
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_MAX_RECORDS = 250
_TIMEOUT_SECONDS = 10.0
_MIN_INTERVAL_SECONDS = 5.5  # GDELT 공식 가이드: 5초에 1요청

# 동시 요청 1개 + 연속 호출 사이 최소 간격 유지
_semaphore = asyncio.Semaphore(1)
_last_request_ts: float = 0.0


class GdeltClient:
    """GDELT Doc 2.0 API 클라이언트 (키워드 + 날짜 범위).

    429/타임아웃 시 즉시 빈 배열을 반환한다 (보조 소스이므로 fast-fail).
    """

    async def fetch_articles(
        self,
        keyword: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        params = {
            "query": keyword,
            "mode": "ArtList",
            "maxrecords": _MAX_RECORDS,
            "startdatetime": start_date.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_date.strftime("%Y%m%d%H%M%S"),
            "format": "json",
        }

        global _last_request_ts
        async with _semaphore:
            elapsed = time.monotonic() - _last_request_ts
            if elapsed < _MIN_INTERVAL_SECONDS:
                await asyncio.sleep(_MIN_INTERVAL_SECONDS - elapsed)
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                    resp = await client.get(_DOC_API, params=params)
                    _last_request_ts = time.monotonic()
                    if resp.status_code == 429:
                        logger.info("[GDELT] 429 rate limit (keyword=%s), skip", keyword)
                        return []
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as exc:
                _last_request_ts = time.monotonic()
                logger.info("[GDELT] 조회 실패 (keyword=%s): %s", keyword, exc)
                return []

        return [
            {
                "date": item.get("seendate", "")[:8],
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "tone": float(item.get("tone", 0.0)),
                "source": "gdelt",
            }
            for item in data.get("articles", [])
        ]
