from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class IntegratedAnalysisResponse(BaseModel):
    ticker: str
    query: str
    overall_signal: str  # bullish | bearish | neutral
    confidence: float
    summary: str
    key_points: list[str]
    sub_results: list[dict]
    execution_time_ms: int
    created_at: Optional[datetime] = None
    business_overview: Optional[dict] = None  # AgentBusinessOverview 직렬화 (캐시 복원용)
