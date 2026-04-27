"""
SnsPostRepositoryPort
=====================
SNS 게시물 영속성 인터페이스. news 도메인의 CollectedNewsRepositoryPort 패턴.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domains.sentiment.domain.entity.sns_post import SnsPost


class SnsPostRepositoryPort(ABC):
    """SNS 게시물 저장소 계약"""

    @abstractmethod
    async def save(self, post: SnsPost) -> SnsPost:
        """게시물 저장. 저장 후 id가 채워진 객체 반환."""
        ...

    @abstractmethod
    async def save_batch(self, posts: list[SnsPost]) -> int:
        """
        여러 건 일괄 저장. 중복(post_hash)은 자동 skip.
        Returns: 실제로 저장된 개수.
        """
        ...

    @abstractmethod
    async def exists_by_hash(self, post_hash: str) -> bool:
        """post_hash 기준 중복 체크"""
        ...

    @abstractmethod
    async def find_by_ticker(
        self,
        ticker: str,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> list[SnsPost]:
        """
        종목 티커로 조회. platform 지정 시 해당 플랫폼만 필터링.
        최신순(collected_at desc) 정렬.
        """
        ...

    @abstractmethod
    async def count_by_ticker(self, ticker: str) -> int:
        """해당 티커의 게시물 총 개수"""
        ...
