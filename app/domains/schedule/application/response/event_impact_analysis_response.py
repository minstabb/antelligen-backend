from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class EventImpactAnalysisItem(BaseModel):
    id: Optional[int] = None
    event_id: int
    event_title: str
    event_country: str
    event_at: datetime
    event_importance: str
    summary: str
    direction: str
    impact_tags: List[str]
    key_drivers: List[str]
    risks: List[str]
    indicator_snapshot: Dict[str, Any]
    model_name: str
    generated_at: datetime
    updated_at: datetime


class UpcomingEventItem(BaseModel):
    event_id: int
    title: str
    country: str
    event_at: datetime
    importance: str
    source: str
    reference_url: Optional[str] = None


class RunEventAnalysisResponse(BaseModel):
    total_events: int
    analyzed_count: int
    skipped_existing: int
    failed_count: int
    start_date: str
    end_date: str
    # 기준일: 실제 오늘 날짜. 주말이면 금요일로 시프트된다.
    reference_date: date
    today: date
    is_weekend_shifted: bool = False
    items: List[EventImpactAnalysisItem]
    # 참고용 — 기준일 익일부터 7일 간 다가오는 경제 일정
    upcoming_events: List[UpcomingEventItem] = []


class ListEventAnalysisResponse(BaseModel):
    # RunEventAnalysisResponse 와 동일 스키마로 통일 — 프론트가 한 개 매퍼로 처리할 수 있게.
    reference_date: date
    today: date
    is_weekend_shifted: bool = False
    items: List[EventImpactAnalysisItem]
    upcoming_events: List[UpcomingEventItem] = []
