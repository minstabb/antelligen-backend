import time

from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.news.application.port.collected_news_repository_port import CollectedNewsRepositoryPort
from app.domains.news.application.port.news_signal_analysis_port import NewsSignalAnalysisPort
from app.domains.news.application.port.ticker_keyword_resolver_port import TickerKeywordResolverPort


class AnalyzeNewsSignalUseCase:
    def __init__(
        self,
        repository: CollectedNewsRepositoryPort,
        analysis_port: NewsSignalAnalysisPort,
        keyword_resolver: TickerKeywordResolverPort,
    ):
        self._repository = repository
        self._analysis_port = analysis_port
        self._keyword_resolver = keyword_resolver

    async def execute(self, ticker: str) -> SubAgentResponse:
        start_ms = int(time.time() * 1000)
        keywords = await self._keyword_resolver.resolve(ticker)

        all_articles = []
        for keyword in keywords:
            articles = await self._repository.find_by_keyword(keyword, limit=20)
            all_articles.extend(articles)

        elapsed_ms = int(time.time() * 1000) - start_ms

        if not all_articles:
            return SubAgentResponse.no_data("news", elapsed_ms)

        company_name = keywords[0] if keywords else ticker

        try:
            signal = await self._analysis_port.analyze(ticker, company_name, all_articles)
        except Exception:
            elapsed_ms = int(time.time() * 1000) - start_ms
            return SubAgentResponse.error("news", "뉴스 감성 분석 중 오류가 발생했습니다.", elapsed_ms)

        elapsed_ms = int(time.time() * 1000) - start_ms
        article_urls = [a.url for a in all_articles if getattr(a, "url", None)]
        return SubAgentResponse.success_with_signal(
            signal, {"ticker": ticker, "article_urls": article_urls}, elapsed_ms
        )
