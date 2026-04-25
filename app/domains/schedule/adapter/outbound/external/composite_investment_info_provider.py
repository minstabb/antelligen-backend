"""여러 InvestmentInfoProviderPort 를 유형별로 라우팅하는 composite 어댑터.

각 provider 의 `supports(info_type)` 결과를 기반으로 첫 매치 provider 에 위임한다.
매치되는 provider 가 없으면 ValueError 를 발생시킨다.
"""

import logging
from typing import Sequence

from app.domains.schedule.application.port.out.investment_info_provider_port import (
    InvestmentInfoProviderPort,
)
from app.domains.schedule.domain.entity.investment_info import InvestmentInfo
from app.domains.schedule.domain.value_object.investment_info_type import InvestmentInfoType

logger = logging.getLogger(__name__)


class CompositeInvestmentInfoProvider(InvestmentInfoProviderPort):
    def __init__(self, providers: Sequence[InvestmentInfoProviderPort]):
        if not providers:
            raise ValueError("최소 1개 이상의 provider 가 필요합니다.")
        self._providers = list(providers)

    def supports(self, info_type: InvestmentInfoType) -> bool:
        return any(self._provider_supports(p, info_type) for p in self._providers)

    async def fetch(self, info_type: InvestmentInfoType) -> InvestmentInfo:
        for provider in self._providers:
            if self._provider_supports(provider, info_type):
                name = provider.__class__.__name__
                print(f"[schedule.composite] {info_type.value} -> {name} 로 라우팅")
                return await provider.fetch(info_type)
        raise ValueError(
            f"지원하는 provider 가 없습니다: {info_type.value}"
        )

    @staticmethod
    def _provider_supports(provider: InvestmentInfoProviderPort, info_type: InvestmentInfoType) -> bool:
        support_fn = getattr(provider, "supports", None)
        if callable(support_fn):
            try:
                return bool(support_fn(info_type))
            except Exception:
                return False
        return True  # supports() 구현 없으면 항상 지원한다고 간주
