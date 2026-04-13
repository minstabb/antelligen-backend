import asyncio

import trafilatura

from app.domains.news.application.port.article_content_provider import (
    ArticleContentProvider,
)


class ArticleContentScraper(ArticleContentProvider):
    """trafilatura 기반 기사 본문 추출 Adapter — 광고/네비게이션 자동 분리"""

    async def fetch_content(self, url: str) -> str:
        return await asyncio.to_thread(self._extract, url)

    @staticmethod
    def _extract(url: str) -> str:
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
