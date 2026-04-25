"""Composite 뉴스 프로바이더.

region 별로 소스 우선순위를 정해 fail-over 체인으로 호출한다.
- 상위 소스가 성공적으로 N건 이상을 돌려주면 하위 소스는 호출하지 않는다 (쿼터 절감).
- 각 호출은 per-source 타임아웃으로 감싸 특정 소스의 지연이 전체 요청을 막지 않게 한다.
- 다음 소스로 fallback 후 합친 결과는 Jaccard 유사도로 중복 제거한다.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Dict, List, Optional

from app.domains.causality_agent.adapter.outbound.external.finnhub_news_client import (
    FinnhubNewsClient,
)
from app.domains.causality_agent.adapter.outbound.external.gdelt_client import GdeltClient
from app.domains.causality_agent.adapter.outbound.external.yahoo_finance_news_client import (
    YahooFinanceNewsClient,
)
from app.domains.history_agent.application.port.out.news_event_port import (
    NewsEventPort,
    NewsItem,
    Region,
)
from app.domains.news.adapter.outbound.external.naver_news_client import NaverNewsClient
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

_PERIOD_DAYS: Dict[str, int] = {
    "1W": 7,
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "2Y": 730,
    "5Y": 1825,
}
_DEFAULT_PERIOD_DAYS = 90

# 지수/ETF용 GDELT 키워드 매핑
_INDEX_KEYWORDS: Dict[str, str] = {
    "^IXIC": "NASDAQ OR \"Nasdaq Composite\"",
    "^GSPC": "\"S&P 500\"",
    "^DJI": "\"Dow Jones\"",
    "^KS11": "KOSPI",
    "SPY": "\"S&P 500\"",
    "QQQ": "NASDAQ",
    "IWM": "\"Russell 2000\"",
    "EWY": "\"KOSPI\" OR \"Korea stocks\"",
}


def _period_to_start(period: str) -> date:
    days = _PERIOD_DAYS.get(period.upper(), _DEFAULT_PERIOD_DAYS)
    return date.today() - timedelta(days=days)


def _parse_yyyymmdd(value: str) -> Optional[date]:
    if not value or len(value) < 8:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _jaccard_similarity(a: str, b: str) -> float:
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _dedup(items: List[NewsItem], threshold: float = 0.8) -> List[NewsItem]:
    """동일 일자 + 제목 Jaccard ≥ threshold 쌍을 상위 아이템 기준 제거.

    입력 순서가 우선순위 — 상위 소스 결과를 먼저 넣으면 하위 소스 중복이 밀린다.
    """
    kept: List[NewsItem] = []
    for candidate in items:
        duplicate = False
        for existing in kept:
            if existing.date != candidate.date:
                continue
            if _jaccard_similarity(existing.title, candidate.title) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


class CompositeNewsProvider(NewsEventPort):
    """Finnhub → GDELT → YahooFinance / Naver 체인.

    클라이언트 인스턴스는 stateless 이므로 모듈 싱글톤으로 재사용해도 안전하다.
    """

    def __init__(
        self,
        finnhub: Optional[FinnhubNewsClient] = None,
        gdelt: Optional[GdeltClient] = None,
        yahoo: Optional[YahooFinanceNewsClient] = None,
        naver: Optional[NaverNewsClient] = None,
    ):
        self._finnhub = finnhub or FinnhubNewsClient()
        self._gdelt = gdelt or GdeltClient()
        self._yahoo = yahoo or YahooFinanceNewsClient()
        settings = get_settings()
        self._naver = naver or NaverNewsClient(
            client_id=settings.naver_client_id,
            client_secret=settings.naver_client_secret,
        )

    async def fetch_news(
        self,
        *,
        ticker: str,
        period: str,
        region: Region,
        top_n: int = 10,
        lookback_days: Optional[int] = None,
    ) -> List[NewsItem]:
        if lookback_days is not None:
            start = date.today() - timedelta(days=lookback_days)
        else:
            start = _period_to_start(period)
        end = date.today()
        timeout = get_settings().history_news_per_source_timeout_s

        if region == "KR":
            sources = self._kr_sources(ticker, start, end)
        elif region == "GLOBAL":
            sources = self._global_sources(ticker, start, end)
        else:
            sources = self._us_sources(ticker, start, end)

        collected: List[NewsItem] = []
        for name, fetch in sources:
            try:
                items = await asyncio.wait_for(fetch(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.info(
                    "[CompositeNews] %s 타임아웃 — 다음 소스로 fallback (ticker=%s)",
                    name, ticker,
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "[CompositeNews] %s 오류 — 다음 소스로 fallback (ticker=%s): %s",
                    name, ticker, exc,
                )
                continue

            if items:
                # 상위 소스에서 결과가 나오면 하위 소스는 호출하지 않는다 (429 감축).
                # 부족할 수 있지만 dedup 비용 + 상류 쿼터 절감이 더 중요하다.
                collected.extend(items)
                break

        deduped = _dedup(collected)
        deduped.sort(key=lambda n: n.date, reverse=True)
        return deduped[:top_n]

    # ── source fetchers ────────────────────────────────────────────

    def _us_sources(
        self, ticker: str, start: date, end: date
    ) -> List[tuple[str, Callable[[], Awaitable[List[NewsItem]]]]]:
        return [
            ("finnhub", lambda: self._fetch_finnhub(ticker, start, end)),
            ("gdelt", lambda: self._fetch_gdelt(ticker, start, end)),
            ("yahoo", lambda: self._fetch_yahoo(ticker, start, end)),
        ]

    def _kr_sources(
        self, ticker: str, start: date, end: date
    ) -> List[tuple[str, Callable[[], Awaitable[List[NewsItem]]]]]:
        return [
            ("naver", lambda: self._fetch_naver(ticker)),
            ("gdelt", lambda: self._fetch_gdelt(ticker, start, end)),
            ("yahoo", lambda: self._fetch_yahoo(ticker, start, end)),
        ]

    def _global_sources(
        self, ticker: str, start: date, end: date
    ) -> List[tuple[str, Callable[[], Awaitable[List[NewsItem]]]]]:
        keyword = _INDEX_KEYWORDS.get(ticker, ticker)

        async def _gdelt_with_keyword() -> List[NewsItem]:
            return await self._fetch_gdelt(keyword, start, end)

        return [
            ("gdelt", _gdelt_with_keyword),
            ("finnhub", lambda: self._fetch_finnhub(ticker, start, end)),
            ("yahoo", lambda: self._fetch_yahoo(ticker, start, end)),
        ]

    async def _fetch_finnhub(
        self, symbol: str, start: date, end: date
    ) -> List[NewsItem]:
        raw = await self._finnhub.fetch_articles(symbol, start, end)
        return [
            NewsItem(
                date=_parse_yyyymmdd(r.get("date", "")) or end,
                title=r.get("title", "").strip(),
                url=r.get("url", ""),
                source="finnhub",
                sentiment=r.get("tone"),
            )
            for r in raw
            if r.get("title")
        ]

    async def _fetch_gdelt(
        self, keyword: str, start: date, end: date
    ) -> List[NewsItem]:
        raw = await self._gdelt.fetch_articles(keyword, start, end)
        return [
            NewsItem(
                date=_parse_yyyymmdd(r.get("date", "")) or end,
                title=r.get("title", "").strip(),
                url=r.get("url", ""),
                source="gdelt",
                sentiment=r.get("tone"),
            )
            for r in raw
            if r.get("title")
        ]

    async def _fetch_yahoo(
        self, symbol: str, start: date, end: date
    ) -> List[NewsItem]:
        raw = await self._yahoo.fetch_articles(symbol, start, end)
        return [
            NewsItem(
                date=_parse_yyyymmdd(r.get("date", "")) or end,
                title=r.get("title", "").strip(),
                url=r.get("url", ""),
                source="yahoo",
                sentiment=r.get("tone"),
            )
            for r in raw
            if r.get("title")
        ]

    async def _fetch_naver(self, ticker: str) -> List[NewsItem]:
        """한국 종목 티커로 NaverNewsClient 검색.

        ticker 가 6자리 숫자 코드라면 그대로 검색어로 쓰고, 회사명 매핑이 있으면 추가 가능.
        현재는 ticker 자체를 키워드로 검색한다 — 호출자가 기업명으로 치환해서 줄 수 있음.
        """
        collected = await self._naver.search(keyword=ticker, display=30, start=1)
        items: List[NewsItem] = []
        for c in collected:
            published = _parse_naver_pubdate(c.published_at) or date.today()
            items.append(
                NewsItem(
                    date=published,
                    title=c.title,
                    url=c.url,
                    source="naver",
                    summary=c.description or None,
                )
            )
        return items


def _parse_naver_pubdate(value: str) -> Optional[date]:
    """Naver pubDate 는 RFC 822 형식 (`Mon, 01 Apr 2026 12:00:00 +0900`)."""
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        return dt.date()
    except (TypeError, ValueError):
        return None
