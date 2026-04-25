from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class EtfHolding:
    ticker: str
    name: str
    weight_pct: float  # 0~100 범위의 비중(%)


class EtfHoldingsPort(ABC):
    @abstractmethod
    async def get_top_holdings(self, etf_ticker: str, top_n: int = 5) -> List[EtfHolding]:
        """ETF의 상위 보유 종목 리스트를 비중 내림차순으로 반환한다.

        데이터 소스 실패 시 빈 리스트를 반환해 상위 레이어가 graceful degradation을 하게 한다.
        """
        raise NotImplementedError
