import time

from app.domains.agent.application.port.disclosure_agent_port import DisclosureAgentPort
from app.domains.agent.application.response.investment_signal_response import (
    InvestmentSignal,
    InvestmentSignalResponse,
)
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.agent.domain.value_object.source_tier import SourceTier
from app.domains.disclosure.application.service.disclosure_analysis_service import (
    DisclosureAnalysisService,
)


class DisclosureSubAgentAdapter(DisclosureAgentPort):
    """공시 분석 서비스를 호출하는 아웃바운드 어댑터."""

    def __init__(self) -> None:
        self._service = DisclosureAnalysisService()

    async def analyze(self, ticker: str) -> SubAgentResponse:
        start = time.monotonic()
        try:
            result = await self._service.analyze(ticker)
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return SubAgentResponse.error("disclosure", str(exc), elapsed)

        elapsed = int((time.monotonic() - start) * 1000)

        if result.status == "error":
            return SubAgentResponse.error(
                "disclosure",
                result.error_message or "공시 분석 실패",
                elapsed,
            )

        if result.signal is None:
            return SubAgentResponse.no_data("disclosure", elapsed)

        try:
            signal_enum = InvestmentSignal(result.signal)
        except ValueError:
            signal_enum = InvestmentSignal.NEUTRAL

        signal_response = InvestmentSignalResponse(
            agent_name="disclosure",
            ticker=ticker,
            signal=signal_enum,
            confidence=result.confidence or 0.0,
            summary=result.summary or "",
            key_points=result.key_points or ["분석 결과 없음"],
        )
        return SubAgentResponse.success_with_signal(
            signal_response, result.data, elapsed
        ).model_copy(update={"source_tier": SourceTier.HIGH})
