from app.domains.news.application.port.news_search_provider import (
    NewsSearchProvider,
    NewsSearchResult,
)
from app.domains.news.domain.entity.news_article import NewsArticle
from app.domains.stock.domain.value_object.market_region import MarketRegion
from app.infrastructure.external.serp_client import SerpClient

_LOCALE_MAP: dict[MarketRegion, tuple[str, str]] = {
    MarketRegion.KR_KOSPI: ("kr", "ko"),
    MarketRegion.KR_KOSDAQ: ("kr", "ko"),
    MarketRegion.KR_KONEX: ("kr", "ko"),
    MarketRegion.US_NYSE: ("us", "en"),
    MarketRegion.US_NASDAQ: ("us", "en"),
    MarketRegion.UNKNOWN: ("kr", "ko"),
}


class SerpNewsSearchProvider(NewsSearchProvider):
    """SerpAPI Google News 검색 어댑터"""

    def __init__(self, api_key: str, market_region: MarketRegion = MarketRegion.KR_KOSPI):
        self._client = SerpClient(api_key=api_key)
        gl, hl = _LOCALE_MAP.get(market_region, ("kr", "ko"))
        self._gl = gl
        self._hl = hl

    async def search(
        self, keyword: str, page: int, page_size: int
    ) -> NewsSearchResult:
        start = (page - 1) * page_size

        params = {
            "engine": "google_news",
            "q": keyword,
            "gl": self._gl,
            "hl": self._hl,
            "start": start,
            "num": page_size,
        }

        data = await self._client.get(params)

        news_results = data.get("news_results", [])

        articles = [
            NewsArticle(
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                source=item.get("source", {}).get("name", "")
                if isinstance(item.get("source"), dict)
                else item.get("source", ""),
                published_at=item.get("date", ""),
                link=item.get("link"),
            )
            for item in news_results
        ]

        total_count = data.get("search_information", {}).get(
            "total_results", len(articles)
        )

        return NewsSearchResult(articles=articles, total_count=total_count)
