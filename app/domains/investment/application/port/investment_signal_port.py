"""
투자 심리 지표 산출 Port (Application Layer).

Outbound Port — 유튜브 댓글 및 뉴스 기사로부터 투자 심리 지표를 산출하는 추상 인터페이스.
"""

from abc import ABC, abstractmethod
from typing import Optional

from app.domains.investment.domain.value_object.news_signal_metrics import NewsSignalMetrics
from app.domains.investment.domain.value_object.youtube_signal_metrics import YoutubeSignalMetrics


class InvestmentSignalPort(ABC):
    """유튜브 댓글 및 뉴스 기사로부터 투자 심리 지표를 산출하는 Port."""

    @abstractmethod
    async def analyze_youtube_comments(
        self,
        comments: list[str],
        company: Optional[str] = None,
    ) -> YoutubeSignalMetrics:
        """
        댓글 텍스트 리스트로부터 감성 분포·키워드·토픽을 산출한다.

        Args:
            comments: 댓글 텍스트 리스트 (빈 리스트 허용 — 기본값 반환).
            company: 종목명 또는 None (프롬프트 컨텍스트용).
        Returns:
            YoutubeSignalMetrics
        Raises:
            Exception: LLM 호출 실패 또는 응답 파싱 오류.
        """
        ...

    @abstractmethod
    async def analyze_news(
        self,
        news_items: list[dict],
        company: Optional[str] = None,
    ) -> NewsSignalMetrics:
        """
        뉴스 기사 리스트로부터 긍정·부정 이벤트 및 키워드를 산출한다.

        Args:
            news_items: 각 항목에 summary_text 또는 title 이 포함된 dict 리스트.
            company: 종목명 또는 None (프롬프트 컨텍스트용).
        Returns:
            NewsSignalMetrics
        Raises:
            Exception: LLM 호출 실패 또는 응답 파싱 오류.
        """
        ...
