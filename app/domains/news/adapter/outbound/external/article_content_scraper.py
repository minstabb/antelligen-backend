import asyncio
import logging

import httpx
import trafilatura

from app.domains.news.application.port.article_content_provider import (
    ArticleContentProvider,
)

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}


class ArticleContentScraper(ArticleContentProvider):
    """trafilatura 기반 기사 본문 추출 Adapter — 브라우저 헤더로 403 우회"""

    async def fetch_content(self, url: str) -> str:
        # 1차: httpx로 브라우저 헤더 요청 후 trafilatura 추출
        try:
            async with httpx.AsyncClient(
                headers=_BROWSER_HEADERS,
                follow_redirects=True,
                timeout=15.0,
            ) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    text = trafilatura.extract(
                        response.text,
                        include_comments=False,
                        include_tables=False,
                        no_fallback=False,
                    )
                    if text:
                        return text
                else:
                    logger.warning("[ArticleContentScraper] HTTP %s for URL %s", response.status_code, url)
        except Exception as e:
            logger.warning("[ArticleContentScraper] httpx 요청 실패: %s", str(e))

        # 2차: trafilatura 기본 방식 fallback
        return await asyncio.to_thread(self._extract_fallback, url)

    @staticmethod
    def _extract_fallback(url: str) -> str:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return ""
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            return text or ""
        except Exception:
            return ""
