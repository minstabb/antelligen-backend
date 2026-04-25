from abc import ABC, abstractmethod

from app.domains.schedule.domain.entity.investment_info import InvestmentInfo
from app.domains.schedule.domain.value_object.investment_info_type import InvestmentInfoType


class InvestmentInfoProviderPort(ABC):
    """외부 데이터 소스에서 특정 투자 정보(금리·유가·환율)를 조회하는 포트."""

    @abstractmethod
    async def fetch(self, info_type: InvestmentInfoType) -> InvestmentInfo:
        ...
