from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScheduleNotification:
    """경제 일정 분석 저장 결과 알림.

    - event_id: 저장 일정 식별자 (경제 일정.id)
    - analysis_id: 성공 시 event_impact_analyses.id
    - stored_at: 저장 시각
    - success: True/False (성공/실패)
    - error_message: 실패 사유 (success=False 일 때 의미 있음)
    - read_at: 사용자가 확인한 시각. None 이면 '미확인' 상태
    """

    event_id: int
    event_title: str
    success: bool
    stored_at: datetime
    analysis_id: Optional[int] = None
    error_message: str = ""
    read_at: Optional[datetime] = None
    id: Optional[int] = field(default=None)
    created_at: Optional[datetime] = None
