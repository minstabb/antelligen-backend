import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import httpx

from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

_COMPANY_NEWS_API = "https://finnhub.io/api/v1/company-news"
_TIMEOUT_SECONDS = 10.0
_MAX_RECORDS = 100


class FinnhubNewsClient:
    """Finnhub company-news API 클라이언트.

    무료 tier 분당 60건. 금융 특화 뉴스로 GDELT보다 노이즈가 적다.
    """

    def __init__(self) -> None:
        self._api_key = get_settings().finnhub_api_key

    async def fetch_articles(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        if not self._api_key:
            logger.info("[Finnhub] API 키 미설정, skip")
            return []

        params = {
            "symbol": symbol,
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "token": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.get(_COMPANY_NEWS_API, params=params)
                if resp.status_code == 429:
                    logger.info("[Finnhub] 429 rate limit (symbol=%s), skip", symbol)
                    return []
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.info("[Finnhub] 조회 실패 (symbol=%s): %s", symbol, exc)
            return []

        if not isinstance(data, list):
            return []

        articles: List[Dict[str, Any]] = []
        for item in data[:_MAX_RECORDS]:
            ts = item.get("datetime")
            if ts:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                date_str = dt.strftime("%Y%m%d")
            else:
                date_str = ""
            articles.append(
                {
                    "date": date_str,
                    "title": item.get("headline", ""),
                    "url": item.get("url", ""),
                    "tone": 0.0,  # Finnhub 자체엔 감성 점수 없음
                    "source": "finnhub",
                }
            )
        return articles
