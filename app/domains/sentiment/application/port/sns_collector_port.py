"""
SNS Collector Port
==================
Reddit, 네이버 종목토론, 토스 등 모든 SNS 플랫폼 수집기의 공통 인터페이스.

이 Port를 구현하면 어떤 플랫폼이든 같은 방식으로 호출 가능:
    posts = await collector.collect(ticker="AAPL", limit=50)

UseCase는 Port 리스트를 받아서 플랫폼별로 순회하면 끝.
새 플랫폼 추가 시 이 Port 구현체만 만들면 됨 (Open-Closed Principle).
"""

from abc import ABC, abstractmethod

from app.domains.sentiment.domain.entity.sns_post import SnsPost


class SnsCollectorPort(ABC):
    """SNS 게시물 수집기 공통 계약"""

    # 구현체는 본인 platform 이름을 클래스 변수로 노출 (예: "reddit")
    platform: str = ""

    @abstractmethod
    async def collect(self, ticker: str, limit: int = 50) -> list[SnsPost]:
        """
        주어진 티커에 대한 게시물을 수집.

        Args:
            ticker: 종목 티커 ("005930" 또는 "AAPL")
            limit: 최대 수집 개수

        Returns:
            SnsPost 리스트. 실패 시 빈 리스트 (예외 던지지 않음).
            한 플랫폼이 죽어도 다른 플랫폼은 계속 동작해야 하므로.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """API 키나 의존성이 갖춰져 있는지 사전 체크."""
        ...
