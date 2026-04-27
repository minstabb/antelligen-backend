"""
AnalyzeSnsSignalUseCase
=======================
ticker → DB에서 최근 게시물 조회 → SnsSignalAnalysisPort로 분석 → SnsSignalResult 반환.

AnalyzeNewsSignalUseCase와 동일 패턴.
TickerKeywordResolverPort 재사용: 회사명 가져오기.
"""

from __future__ import annotations

import logging
import time

from app.domains.news.application.port.ticker_keyword_resolver_port import TickerKeywordResolverPort
from app.domains.sentiment.application.port.sns_post_repository_port import SnsPostRepositoryPort
from app.domains.sentiment.application.port.sns_signal_analysis_port import SnsSignalAnalysisPort
from app.domains.sentiment.application.response.analyze_sns_signal_response import SnsSignalResult

logger = logging.getLogger(__name__)


class AnalyzeSnsSignalUseCase:
    def __init__(
        self,
        repository: SnsPostRepositoryPort,
        analysis_port: SnsSignalAnalysisPort,
        keyword_resolver: TickerKeywordResolverPort,
    ):
        self._repository = repository
        self._analysis_port = analysis_port
        self._keyword_resolver = keyword_resolver

    async def execute(
        self,
        ticker: str,
        lookback_limit: int = 100,
    ) -> SnsSignalResult:
        start_ms = time.monotonic()

        # 회사명 조회 (GPT 프롬프트 품질 개선용)
        keywords = await self._keyword_resolver.resolve(ticker)
        company_name = keywords[0] if keywords else ticker

        # DB에서 최근 게시물 조회
        posts = await self._repository.find_by_ticker(ticker, limit=lookback_limit)

        if not posts:
            elapsed_ms = int((time.monotonic() - start_ms) * 1000)
            logger.info(f"AnalyzeSnsSignalUseCase: 게시물 없음, ticker={ticker}")
            return SnsSignalResult(
                ticker=ticker,
                signal="neutral",
                confidence=0.0,
                total_sample_size=0,
                reasoning="분석할 SNS 게시물이 없습니다.",
                elapsed_ms=elapsed_ms,
            )

        # 감정분석 실행
        result = await self._analysis_port.analyze(ticker, company_name, posts)

        # elapsed_ms는 analysis_port 내부에서도 측정되지만,
        # UseCase 전체 시간으로 덮어쓴다
        result.elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        logger.info(
            f"SNS 감정분석 완료: ticker={ticker}, signal={result.signal}, "
            f"confidence={result.confidence:.2f}, samples={result.total_sample_size}"
        )

        return result
