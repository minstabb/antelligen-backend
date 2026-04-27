"""
Toss Community Client (stub)
=============================
토스 주식판 수집기 — 인터페이스만 구현. 실제 동작 미구현.

이유:
    토스 커뮤니티는 공개 API 없음. 앱 내 WebView 기반으로 정적 스크래핑 불가.
    추후 앱 리버스엔지니어링 또는 공식 파트너십 시 구현 예정.

TODO: 구현 시 SnsCollectorPort.collect() 시그니처 그대로 유지.
"""

from __future__ import annotations

import logging

from app.domains.sentiment.application.port.sns_collector_port import SnsCollectorPort
from app.domains.sentiment.domain.entity.sns_post import SnsPost

logger = logging.getLogger(__name__)


class TossCommunityClient(SnsCollectorPort):
    """토스 주식판 수집기 (미구현 stub)"""

    platform = "toss_community"

    def is_available(self) -> bool:
        """미구현 — 항상 False 반환하여 수집 파이프라인에서 자동 skip"""
        return False

    async def collect(self, ticker: str, limit: int = 50) -> list[SnsPost]:
        """미구현. 호출되면 경고 로그 + 빈 리스트 반환."""
        logger.warning(
            "TossCommunityClient.collect() 호출됨 — 아직 미구현. 빈 리스트 반환."
        )
        return []
