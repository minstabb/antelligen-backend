"""
투자 판단 산출 Port (Application Layer).

Outbound Port — 뉴스·유튜브 심리 지표로부터 구조화된 투자 판단을 산출하는 추상 인터페이스.
"""

from abc import ABC, abstractmethod
from typing import Optional

from app.domains.investment.domain.value_object.investment_decision import InvestmentDecision
from app.domains.investment.domain.value_object.news_signal_metrics import NewsSignalMetrics
from app.domains.investment.domain.value_object.youtube_signal_metrics import YoutubeSignalMetrics


class InvestmentDecisionPort(ABC):
    """뉴스·유튜브 심리 지표로부터 buy / hold / sell 판단을 산출하는 Port."""

    @abstractmethod
    async def analyze(
        self,
        *,
        news_signal: Optional[NewsSignalMetrics],
        youtube_signal: Optional[YoutubeSignalMetrics],
        company: Optional[str],
        intent: str,
    ) -> InvestmentDecision:
        """
        두 신호를 결합하여 InvestmentDecision을 반환한다.

        - direction / confidence / verdict 는 deterministic rule 기반으로 계산.
        - reasons / risk_factors / rationale 는 LLM을 통해 생성.
        - 신호 부족 시 보수적 fallback(hold + confidence≤0.3)을 반환.
        """
        ...
