from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class EventImpactAnalysis:
    """경제 일정 1건에 대한 영향 분석 결과.

    - event_id: 대상 economic_event.id
    - summary: 3-5 문장 한국어 요약
    - direction: bullish/bearish/neutral/mixed
    - impact_tags: 인플레이션/유동성/위험자산 등 태그
    - key_drivers / risks: bullet 리스트
    - indicator_snapshot: 분석 시점의 매크로 지표 스냅샷 {type: {value, unit, source, ...}}
    """

    event_id: int
    summary: str
    direction: str
    impact_tags: List[str]
    key_drivers: List[str]
    risks: List[str]
    indicator_snapshot: Dict[str, Any]
    model_name: str
    generated_at: datetime
    updated_at: datetime
    id: Optional[int] = field(default=None)
