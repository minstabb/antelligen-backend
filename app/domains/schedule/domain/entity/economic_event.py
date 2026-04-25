from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.domains.schedule.domain.value_object.event_importance import EventImportance


@dataclass
class EconomicEvent:
    """주요 경제 일정 도메인 엔티티.

    - source_event_id: 외부 소스 내에서 유일한 식별자 (예: fred-release-9-2026-04-15).
      (source, source_event_id) 조합으로 중복 판별한다.
    """

    source: str
    source_event_id: str
    title: str
    country: str
    event_at: datetime
    importance: EventImportance
    description: str = ""
    reference_url: Optional[str] = None
    id: Optional[int] = field(default=None)
