import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import yfinance as yf

logger = logging.getLogger(__name__)

_MAX_RECORDS = 50


def _fetch_sync(symbol: str) -> List[Dict[str, Any]]:
    try:
        return yf.Ticker(symbol).news or []
    except Exception as exc:
        logger.info("[YahooFinanceNews] 조회 실패 (symbol=%s): %s", symbol, exc)
        return []


def _extract_title(item: Dict[str, Any]) -> str:
    # yfinance 버전별로 스키마가 다름 (flat vs content 래핑)
    if item.get("title"):
        return item["title"]
    content = item.get("content") or {}
    return content.get("title", "")


def _extract_url(item: Dict[str, Any]) -> str:
    if item.get("link"):
        return item["link"]
    content = item.get("content") or {}
    canonical = content.get("canonicalUrl") or {}
    return canonical.get("url", "") or content.get("clickThroughUrl", {}).get("url", "")


def _extract_publish_dt(item: Dict[str, Any]) -> datetime | None:
    ts = item.get("providerPublishTime")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)

    content = item.get("content") or {}
    pub = content.get("pubDate") or content.get("displayTime")
    if isinstance(pub, str):
        try:
            return datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class YahooFinanceNewsClient:
    """yfinance `.news` 기반 fallback 뉴스 소스.

    Yahoo Finance 뉴스 피드는 날짜 범위 검색이 없어 최신 N건만 반환된다.
    클라이언트 측에서 날짜 필터링한다.
    """

    async def fetch_articles(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        raw = await asyncio.to_thread(_fetch_sync, symbol)
        if not raw:
            return []

        articles: List[Dict[str, Any]] = []
        for item in raw[:_MAX_RECORDS]:
            dt = _extract_publish_dt(item)
            if dt is None:
                continue
            pub_date = dt.date()
            if pub_date < start_date or pub_date > end_date:
                continue
            title = _extract_title(item)
            if not title:
                continue
            articles.append(
                {
                    "date": dt.strftime("%Y%m%d"),
                    "title": title,
                    "url": _extract_url(item),
                    "tone": 0.0,
                    "source": "yfinance",
                }
            )
        return articles
