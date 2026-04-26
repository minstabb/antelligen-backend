from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class EventImpactMetric:
    """이벤트 임팩트 메트릭 Aggregate Root.

    EventEnrichment(LLM 부산물 캐시)와 분리. 캐시 무효화 차원이 다르다 —
    enrichment는 classifier_version, impact는 bars_data_version.

    UK: (ticker, event_date, event_type, detail_hash, pre_days, post_days).
    detail_hash는 history_agent.compute_detail_hash와 동일한 알고리즘으로 생성하여
    enrichment 행과 join 가능.
    """

    ticker: str
    event_date: date
    event_type: str
    detail_hash: str
    benchmark_ticker: str
    pre_days: int                              # 보통 -1 (event 직전 거래일)
    post_days: int                             # +5 또는 +20
    status: str                                # EventImpactStatus 값
    cumulative_return_pct: Optional[float] = field(default=None)
    benchmark_return_pct: Optional[float] = field(default=None)
    abnormal_return_pct: Optional[float] = field(default=None)
    sample_completeness: float = field(default=0.0)
    bars_data_version: Optional[str] = field(default=None)
    id: Optional[int] = field(default=None)
    computed_at: Optional[datetime] = field(default=None)
