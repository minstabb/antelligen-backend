"""
SnsSignalAnalysisPort
=====================
SNS 게시물 묶음 → 감정 시그널 변환 인터페이스.
GPT가 됐든, 다른 LLM이든, 단순 키워드 분석이든 구현체에서 결정.

회의록 4번의 핵심 — "댓글 같은 거 sns에서 감정 분석".
"""

from abc import ABC, abstractmethod

from app.domains.sentiment.application.response.analyze_sns_signal_response import (
    SnsSignalResult,
)
from app.domains.sentiment.domain.entity.sns_post import SnsPost


class SnsSignalAnalysisPort(ABC):
    """SNS 감정분석기 공통 계약"""

    @abstractmethod
    async def analyze(
        self,
        ticker: str,
        company_name: str,
        posts: list[SnsPost],
    ) -> SnsSignalResult:
        """
        게시물 리스트 → 종합 감정 시그널.

        Args:
            ticker: 분석 대상 종목
            company_name: GPT 프롬프트에 넣을 회사명 (한글 또는 영문)
            posts: 분석 대상 게시물들 (여러 플랫폼 섞여있을 수 있음)

        Returns:
            SnsSignalResult — bullish/bearish/neutral + confidence + 부정비율 등
        """
        ...
