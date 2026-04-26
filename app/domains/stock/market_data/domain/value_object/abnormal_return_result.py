from dataclasses import dataclass
from typing import Optional

from app.domains.stock.market_data.domain.value_object.event_impact_status import (
    EventImpactStatus,
)


@dataclass(frozen=True)
class AbnormalReturnResult:
    """AbnormalReturnCalculator.compute() 반환 — Aggregate 저장 전 계산 부산물."""

    status: EventImpactStatus
    cumulative_return_pct: Optional[float] = None    # 종목 t-1 → t+N 누적 수익률 (%)
    benchmark_return_pct: Optional[float] = None     # 벤치마크 동기간 수익률 (%)
    abnormal_return_pct: Optional[float] = None      # 종목 - 벤치마크 (%)
    sample_completeness: float = 0.0                 # 0.0~1.0 거래일 가용성
