"""한국 종목 인과 분석용 Naver News 어댑터.

`news` 도메인의 Naver 어댑터와 별개로, causality_agent의 `_collect_news` 시그니처
(`fetch_articles(ticker, start_date, end_date)`)와 응답 dict 스키마(date/title/url/tone/source)에
맞춘다. Naver OpenAPI는 date filter 미지원이므로 호출 측에서 pubDate 기반으로 잘라낸다.
"""

import logging
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List

import httpx

from app.infrastructure.config.settings import get_settings
from app.infrastructure.external.korean_company_directory import lookup_korean_name

logger = logging.getLogger(__name__)

_BASE_URL = "https://openapi.naver.com/v1/search/news.json"
_TIMEOUT_SECONDS = 10.0
_DISPLAY_PER_PAGE = 100
_MAX_PAGES = 3  # 100건 × 3페이지 = 최대 300건 스캔 후 범위 필터
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class NaverKoreanNewsClient:
    """한국 종목 ticker → 한글 회사명 키워드 → Naver 검색 + pubDate 범위 필터."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.naver_client_id
        self._client_secret = settings.naver_client_secret

    async def fetch_articles(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        if not self._client_id or not self._client_secret:
            logger.info("[NaverKR] Naver API 키 미설정, skip")
            return []

        keyword = lookup_korean_name(ticker) or ticker.upper().split(".")[0]

        headers = {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
        }
        articles: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                for page in range(_MAX_PAGES):
                    params = {
                        "query": keyword,
                        "display": _DISPLAY_PER_PAGE,
                        "start": page * _DISPLAY_PER_PAGE + 1,
                        "sort": "date",
                    }
                    resp = await client.get(_BASE_URL, headers=headers, params=params)
                    if resp.status_code == 429:
                        logger.info("[NaverKR] 429 rate limit (keyword=%s)", keyword)
                        break
                    resp.raise_for_status()
                    items = resp.json().get("items", [])
                    if not items:
                        break

                    page_in_range, oldest_dt = self._normalize_items(items, start_date, end_date)
                    articles.extend(page_in_range)

                    # sort=date 라 가장 오래된 항목이 start_date 보다 과거면 더 볼 필요 없음
                    if oldest_dt is not None and oldest_dt.date() < start_date:
                        break
        except Exception as exc:
            logger.info("[NaverKR] 조회 실패 (keyword=%s): %s", keyword, exc)
            return articles

        logger.info(
            "[NaverKR] keyword=%s, range=%s~%s, hits=%d",
            keyword, start_date, end_date, len(articles),
        )
        return articles

    @staticmethod
    def _normalize_items(
        items: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
    ) -> tuple[List[Dict[str, Any]], datetime | None]:
        """범위 내 항목만 정규화하여 반환 + 페이지에서 본 가장 오래된 datetime."""
        out: List[Dict[str, Any]] = []
        oldest: datetime | None = None
        for item in items:
            pub_dt = _parse_pub_date(item.get("pubDate", ""))
            if pub_dt is None:
                continue
            if oldest is None or pub_dt < oldest:
                oldest = pub_dt
            d = pub_dt.date()
            if d < start_date or d > end_date:
                continue
            url = item.get("originallink") or item.get("link") or ""
            if not url:
                continue
            out.append(
                {
                    "date": pub_dt.strftime("%Y%m%d"),
                    "title": _strip_html(item.get("title", "")),
                    "url": url,
                    "tone": 0.0,
                    "source": "naver",
                }
            )
        return out, oldest


def _parse_pub_date(pub_date: str) -> datetime | None:
    if not pub_date:
        return None
    try:
        return parsedate_to_datetime(pub_date)
    except (TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()
