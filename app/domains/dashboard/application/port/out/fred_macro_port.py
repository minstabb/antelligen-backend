from abc import ABC, abstractmethod
from typing import List

from app.domains.dashboard.domain.entity.macro_data_point import MacroDataPoint


class FredMacroPort(ABC):
    @abstractmethod
    async def fetch_series(self, series_id: str, months: int) -> List[MacroDataPoint]:
        """FRED에서 특정 시리즈의 최근 N개월 데이터를 조회한다.

        Args:
            series_id: FRED Series ID (예: FEDFUNDS, CPIAUCSL, UNRATE)
            months: 조회할 개월 수

        Returns:
            MacroDataPoint 리스트 (날짜 오름차순)

        Raises:
            FredApiException: FRED API 호출 실패 시
        """
        pass
