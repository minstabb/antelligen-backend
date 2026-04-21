import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.agent.adapter.outbound.source_credibility_registry import SourceCredibilityRegistry
from app.domains.agent.application.port.news_agent_port import NewsAgentPort
from app.domains.agent.application.response.sub_agent_response import AgentStatus, SubAgentResponse
from app.domains.agent.domain.value_object.source_tier import SourceTier, _DEFAULT_WEIGHTS, default_multiplier
from app.domains.news.adapter.outbound.external.naver_news_client import NaverNewsClient
from app.domains.news.adapter.outbound.external.openai_news_signal_adapter import OpenAINewsSignalAdapter
from app.domains.news.adapter.outbound.external.serp_news_search_provider import SerpNewsSearchProvider
from app.domains.news.adapter.outbound.persistence.collected_news_repository_impl import CollectedNewsRepositoryImpl
from app.domains.news.adapter.outbound.ticker_keyword_resolver import TickerKeywordResolver
from app.domains.news.application.usecase.analyze_news_signal_usecase import AnalyzeNewsSignalUseCase
from app.domains.news.application.usecase.collect_naver_news_usecase import CollectNaverNewsUseCase
from app.domains.news.domain.entity.collected_news import CollectedNews
from app.domains.news.domain.entity.news_article import NewsArticle
from app.domains.stock.adapter.outbound.persistence.hardcoded_sector_lookup import HardcodedSectorLookup
from app.domains.stock.adapter.outbound.persistence.stock_repository_impl import StockRepositoryImpl
from app.domains.stock.domain.service.market_region_resolver import MarketRegionResolver
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


class NewsSubAgentAdapter(NewsAgentPort):
    def __init__(self, db: AsyncSession, api_key: str):
        self._db = db
        self._api_key = api_key

    async def analyze(self, ticker: str, query: str) -> SubAgentResponse:
        settings = get_settings()
        stock = await StockRepositoryImpl().find_by_ticker(ticker)
        market_hint = stock.market if stock else None
        region = MarketRegionResolver.resolve(ticker, market_hint)

        if region.is_us() and settings.enable_us_tickers:
            return await self._analyze_us(ticker, settings)

        # KR 경로 (기존)
        keyword_resolver = TickerKeywordResolver(StockRepositoryImpl())
        repository = CollectedNewsRepositoryImpl(self._db)
        analysis_port = OpenAINewsSignalAdapter(api_key=self._api_key)
        usecase = AnalyzeNewsSignalUseCase(
            repository=repository,
            analysis_port=analysis_port,
            keyword_resolver=keyword_resolver,
        )

        result = await usecase.execute(ticker)
        if result.status == AgentStatus.NO_DATA:
            keywords = await keyword_resolver.resolve(ticker)
            if not keywords:
                return result
            logger.info("[NewsSubAgent] No news for %s — auto-collecting keywords: %s", ticker, keywords)
            await self._collect(keywords)
            result = await usecase.execute(ticker)

        if result.is_success():
            urls = (result.data or {}).get("article_urls", [])
            sector = await HardcodedSectorLookup().get_sector(ticker)
            tier = _compute_average_tier(urls, sector)
            result = result.model_copy(update={"source_tier": tier})
        return result

    async def _analyze_us(self, ticker: str, settings) -> SubAgentResponse:
        """US 종목: SerpAPI 직접 검색 → OpenAI 분석 (DB 수집 없음)"""
        start_ms = int(time.time() * 1000)
        from app.domains.stock.domain.value_object.market_region import MarketRegion

        provider = SerpNewsSearchProvider(
            api_key=settings.serp_api_key,
            market_region=MarketRegion.US_NASDAQ,
        )
        try:
            result = await provider.search(keyword=ticker, page=1, page_size=15)
            articles = result.articles
        except Exception as e:
            elapsed = int(time.time() * 1000) - start_ms
            return SubAgentResponse.error("news", f"US 뉴스 검색 실패: {e}", elapsed)

        if not articles:
            elapsed = int(time.time() * 1000) - start_ms
            return SubAgentResponse.no_data("news", elapsed)

        collected = [_article_to_collected(a, ticker) for a in articles]
        analysis_port = OpenAINewsSignalAdapter(api_key=settings.openai_api_key)
        try:
            signal = await analysis_port.analyze(ticker, ticker, collected)
        except Exception as e:
            elapsed = int(time.time() * 1000) - start_ms
            return SubAgentResponse.error("news", f"US 뉴스 분석 실패: {e}", elapsed)

        elapsed = int(time.time() * 1000) - start_ms
        urls = [a.link for a in articles if getattr(a, "link", None)]
        sector = await HardcodedSectorLookup().get_sector(ticker)
        tier = _compute_average_tier(urls, sector)
        return SubAgentResponse.success_with_signal(
            signal, {"ticker": ticker, "article_urls": urls}, elapsed
        ).model_copy(update={"source_tier": tier})

    async def _collect(self, keywords: list[str]) -> None:
        settings = get_settings()
        collect_usecase = CollectNaverNewsUseCase(
            naver_news_port=NaverNewsClient(
                client_id=settings.naver_client_id,
                client_secret=settings.naver_client_secret,
            ),
            repository=CollectedNewsRepositoryImpl(self._db),
        )
        await collect_usecase.execute(keywords=keywords)


def _article_to_collected(article: NewsArticle, keyword: str) -> CollectedNews:
    return CollectedNews(
        title=article.title,
        description=article.snippet,
        url=article.link or "",
        published_at=article.published_at,
        keyword=keyword,
    )


def _compute_average_tier(urls: list[str], sector) -> SourceTier:
    """URL 목록을 분류해 가중 평균과 가장 가까운 SourceTier를 반환."""
    registry = SourceCredibilityRegistry()
    weights = [default_multiplier(registry.classify(url, sector)) for url in urls if url]
    if not weights:
        return SourceTier.MEDIUM
    avg = sum(weights) / len(weights)
    return min(_DEFAULT_WEIGHTS.items(), key=lambda kv: abs(kv[1] - avg))[0]
