"""
CollectSnsPostsUseCase
======================
여러 SnsCollectorPort를 받아서 ticker별 게시물 수집 → DB 적재.

asyncio.gather로 플랫폼 병렬 수집.
한 플랫폼 실패해도 나머지는 계속 진행.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.domains.sentiment.application.port.sns_collector_port import SnsCollectorPort
from app.domains.sentiment.application.port.sns_post_repository_port import SnsPostRepositoryPort
from app.domains.sentiment.application.response.collect_sns_posts_response import CollectSnsPostsResponse

logger = logging.getLogger(__name__)


class CollectSnsPostsUseCase:
    def __init__(
        self,
        collectors: list[SnsCollectorPort],
        repository: SnsPostRepositoryPort,
    ):
        self._collectors = collectors
        self._repository = repository

    async def execute(
        self,
        ticker: str,
        limit_per_platform: int = 50,
    ) -> CollectSnsPostsResponse:
        start_ms = time.monotonic()

        # 사용 가능한 collector만 필터링
        available = [c for c in self._collectors if c.is_available()]
        if not available:
            logger.warning(f"CollectSnsPostsUseCase: 사용 가능한 collector 없음, ticker={ticker}")
            return CollectSnsPostsResponse(
                ticker=ticker,
                total_collected=0,
                total_saved=0,
                skipped_duplicates=0,
                elapsed_ms=0,
            )

        # 병렬 수집
        results = await asyncio.gather(
            *[self._collect_one(c, ticker, limit_per_platform) for c in available],
            return_exceptions=True,
        )

        total_collected = 0
        total_saved = 0
        per_platform: dict[str, dict] = {}

        for collector, result in zip(available, results):
            platform = collector.platform

            if isinstance(result, Exception):
                logger.warning(f"[{platform}] 수집 실패: {result}")
                per_platform[platform] = {"collected": 0, "saved": 0, "error": str(result)}
                continue

            posts, saved = result
            collected = len(posts)
            total_collected += collected
            total_saved += saved
            per_platform[platform] = {"collected": collected, "saved": saved}

        skipped = total_collected - total_saved
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        logger.info(
            f"SNS 수집 완료: ticker={ticker}, "
            f"collected={total_collected}, saved={total_saved}, skipped={skipped}"
        )

        return CollectSnsPostsResponse(
            ticker=ticker,
            total_collected=total_collected,
            total_saved=total_saved,
            skipped_duplicates=skipped,
            per_platform=per_platform,
            elapsed_ms=elapsed_ms,
        )

    async def _collect_one(
        self,
        collector: SnsCollectorPort,
        ticker: str,
        limit: int,
    ) -> tuple[list, int]:
        """단일 플랫폼 수집 + DB 저장. (collected_posts, saved_count) 반환."""
        posts = await collector.collect(ticker, limit)
        if not posts:
            return posts, 0
        saved = await self._repository.save_batch(posts)
        return posts, saved
