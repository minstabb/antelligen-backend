import json
import logging
import time

from openai import AsyncOpenAI

from app.common.exception.app_exception import AppException
from app.domains.agent.application.port.finance_agent_port import FinanceAgentPort
from app.domains.agent.application.request.finance_analysis_request import FinanceAnalysisRequest
from app.domains.agent.application.response.investment_signal_response import InvestmentSignal, InvestmentSignalResponse
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.agent.domain.value_object.source_tier import SourceTier
from app.domains.agent.application.usecase.analyze_finance_agent_usecase import (
    AnalyzeFinanceAgentUseCase,
)
from app.domains.agent.adapter.outbound.external.langgraph_finance_agent_provider import (
    LangGraphFinanceAgentProvider,
)
from app.domains.stock.adapter.outbound.external.opendart_financial_data_provider import (
    OpenDartFinancialDataProvider,
)
from app.domains.stock.adapter.outbound.external.openai_stock_embedding_generator import (
    OpenAIStockEmbeddingGenerator,
)
from app.domains.stock.adapter.outbound.external.serp_stock_data_collector import (
    SerpStockDataCollector,
)
from app.domains.stock.adapter.outbound.external.opendart_preliminary_earnings_provider import (
    OpenDartPreliminaryEarningsProvider,
)
from app.domains.stock.adapter.outbound.external.yfinance_financial_data_provider import (
    YfinanceFinancialDataProvider,
)
from app.domains.stock.adapter.outbound.persistence.corp_code_repository_impl import (
    CorpCodeRepositoryImpl,
)
from app.domains.stock.application.usecase.fetch_preliminary_earnings_usecase import (
    FetchPreliminaryEarningsUseCase,
)
from app.domains.stock.adapter.outbound.persistence.stock_repository_impl import (
    StockRepositoryImpl,
)
from app.domains.stock.adapter.outbound.persistence.stock_vector_repository_impl import (
    StockVectorRepositoryImpl,
)
from app.domains.stock.application.usecase.collect_stock_data_usecase import (
    CollectStockDataUseCase,
)
from app.domains.stock.application.usecase.fetch_dart_financial_ratios_usecase import (
    FetchDartFinancialRatiosUseCase,
)
from app.domains.stock.application.usecase.get_stored_stock_data_usecase import (
    GetStoredStockDataUseCase,
)
from app.domains.stock.domain.service.market_region_resolver import MarketRegionResolver
from app.domains.stock.infrastructure.mapper.serp_stock_data_standardizer import (
    SerpStockDataStandardizer,
)
from app.domains.stock.infrastructure.mapper.simple_stock_document_chunker import (
    SimpleStockDocumentChunker,
)
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

_US_FINANCE_SYSTEM_PROMPT = """You are an investment analyst specializing in US equities.
Analyze the provided financial data and return a JSON signal assessment.

Respond ONLY with this JSON (no markdown):
{
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0-1.0>,
  "summary": "<2-3 sentence investment perspective>",
  "key_points": ["<point with numbers>", ...]
}"""


class FinanceSubAgentAdapter(FinanceAgentPort):
    """재무 분석 UseCase를 호출하는 아웃바운드 어댑터.

    벡터 DB에 데이터가 없으면 자동으로 수집 후 재시도한다.
    """

    async def analyze(self, ticker: str, query: str) -> SubAgentResponse:
        settings = get_settings()
        stock = await StockRepositoryImpl().find_by_ticker(ticker)
        market_hint = stock.market if stock else None
        region = MarketRegionResolver.resolve(ticker, market_hint)

        if region.is_us() and settings.enable_us_tickers:
            return await self._analyze_us(ticker, settings)

        # KR 경로 (기존)
        start = time.monotonic()
        try:
            stock_repository = StockRepositoryImpl()
            stock_vector_repository = StockVectorRepositoryImpl()

            get_stored_stock_data_usecase = GetStoredStockDataUseCase(
                stock_repository=stock_repository,
                stock_vector_repository=stock_vector_repository,
            )
            finance_provider = LangGraphFinanceAgentProvider(
                api_key=settings.openai_api_key,
                chat_model=settings.openai_finance_agent_model,
                embedding_model=settings.openai_embedding_model,
                top_k=settings.finance_rag_top_k,
                langsmith_tracing=settings.langsmith_tracing,
                langsmith_api_key=settings.langsmith_api_key,
                langsmith_project=settings.langsmith_project,
                langsmith_endpoint=settings.langsmith_endpoint,
            )
            usecase = AnalyzeFinanceAgentUseCase(
                stock_repository=stock_repository,
                get_stored_stock_data_usecase=get_stored_stock_data_usecase,
                finance_agent_provider=finance_provider,
            )

            request = FinanceAnalysisRequest(ticker=ticker, query=query)
            try:
                result = await usecase.execute(request)
            except AppException as e:
                if e.status_code != 404:
                    raise
                logger.info("[FinanceSubAgent] No stored data for %s — auto-collecting", ticker)
                await self._collect(ticker, settings)
                result = await usecase.execute(request)

            elapsed = int((time.monotonic() - start) * 1000)
            if result.agent_results:
                sub = result.agent_results[0]
                sub = await _enrich_with_preliminary_earnings(sub, ticker)
                return sub.model_copy(update={"source_tier": SourceTier.HIGH})
            return SubAgentResponse.no_data("finance", elapsed)

        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return SubAgentResponse.error("finance", str(exc), elapsed)

    @staticmethod
    async def _analyze_us(ticker: str, settings) -> SubAgentResponse:
        """US 종목: yfinance → OpenAI 직접 분석 (RAG 없음)"""
        start = time.monotonic()
        try:
            provider = YfinanceFinancialDataProvider()
            ratio = await provider.fetch_financial_ratios(ticker)
            earnings = await provider.fetch_recent_earnings(ticker)

            if ratio is None and earnings is None:
                elapsed = int((time.monotonic() - start) * 1000)
                return SubAgentResponse.no_data("finance", elapsed)

            text = _format_us_finance_text(ticker, ratio, earnings)
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model=settings.openai_finance_agent_model,
                messages=[
                    {"role": "system", "content": _US_FINANCE_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            data = json.loads(resp.choices[0].message.content.strip())
            signal_response = InvestmentSignalResponse(
                agent_name="finance",
                ticker=ticker,
                signal=InvestmentSignal(data["signal"]),
                confidence=float(data["confidence"]),
                summary=data["summary"],
                key_points=data.get("key_points", []),
            )
            elapsed = int((time.monotonic() - start) * 1000)
            return SubAgentResponse.success_with_signal(
                signal_response, {"ticker": ticker}, elapsed
            ).model_copy(update={"source_tier": SourceTier.HIGH})

        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return SubAgentResponse.error("finance", f"US 재무 분석 실패: {exc}", elapsed)

    @staticmethod
    async def _collect(ticker: str, settings) -> None:
        dart_financial_ratios_usecase = None
        if settings.open_dart_api_key:
            dart_financial_ratios_usecase = FetchDartFinancialRatiosUseCase(
                corp_code_repository=CorpCodeRepositoryImpl(),
                dart_financial_data_provider=OpenDartFinancialDataProvider(
                    api_key=settings.open_dart_api_key
                ),
            )
        collect_usecase = CollectStockDataUseCase(
            stock_repository=StockRepositoryImpl(),
            stock_data_collector=SerpStockDataCollector(api_key=settings.serp_api_key),
            stock_data_standardizer=SerpStockDataStandardizer(),
            stock_document_chunker=SimpleStockDocumentChunker(),
            stock_embedding_generator=OpenAIStockEmbeddingGenerator(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
            ),
            stock_vector_repository=StockVectorRepositoryImpl(),
            dart_financial_ratios_usecase=dart_financial_ratios_usecase,
        )
        await collect_usecase.execute(ticker)


async def _enrich_with_preliminary_earnings(sub: SubAgentResponse, ticker: str) -> SubAgentResponse:
    """KR 종목의 잠정실적이 있으면 key_points에 추가."""
    try:
        prelim_usecase = FetchPreliminaryEarningsUseCase(
            corp_code_repository=CorpCodeRepositoryImpl(),
            preliminary_earnings_port=OpenDartPreliminaryEarningsProvider(),
        )
        prelim = await prelim_usecase.execute(ticker)
    except Exception:
        return sub

    if prelim is None:
        return sub

    point = f"[잠정실적] {prelim.title} (접수일: {prelim.report_date})"
    updated_points = list(sub.key_points or []) + [point]
    return sub.model_copy(update={"key_points": updated_points})


def _format_us_finance_text(ticker: str, ratio, earnings) -> str:
    lines = [f"[{ticker} Financial Summary]"]
    if ratio:
        lines += [
            f"PER: {ratio.per}",
            f"PBR: {ratio.pbr}",
            f"ROE: {ratio.roe}%",
            f"ROA: {ratio.roa}%",
            f"Debt Ratio: {ratio.debt_ratio}%",
            f"Revenue: {ratio.sales}",
            f"Operating Income: {ratio.operating_income}",
            f"Net Income: {ratio.net_income}",
        ]
    if earnings:
        lines += [
            f"\n[Recent Earnings]",
            f"Report Date: {earnings.report_date}",
            f"EPS: {earnings.eps}",
            f"Revenue: {earnings.revenue}",
        ]
    return "\n".join(lines)
