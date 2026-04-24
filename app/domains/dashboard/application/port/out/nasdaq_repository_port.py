from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional

from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar


class NasdaqRepositoryPort(ABC):
    @abstractmethod
    async def find_latest_bar_date(self) -> Optional[date]:
        """nasdaq_bars 테이블에 저장된 가장 최근 bar_date를 반환한다.

        데이터가 없으면 None을 반환한다.
        """
        pass

    @abstractmethod
    async def upsert_bulk(self, bars: List[NasdaqBar]) -> int:
        """nasdaq_bars 테이블에 일봉 데이터를 upsert한다.

        bar_date 기준으로 충돌 시 OHLCV 값을 갱신한다.

        Returns:
            저장(insert + update)된 행 수
        """
        pass

    @abstractmethod
    async def find_by_date_range(self, start: date, end: date) -> List[NasdaqBar]:
        """기간 범위로 나스닥 일봉 데이터를 조회한다."""
        pass
