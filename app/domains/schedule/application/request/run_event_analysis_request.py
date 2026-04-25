from typing import List, Optional

from pydantic import BaseModel, Field


class RunEventAnalysisRequest(BaseModel):
    """경제 일정 영향 분석 실행 요청.

    - days_back / days_forward: 오늘 기준 ± 일수 범위 (기본 ±14일)
    - importance_levels: HIGH/MEDIUM/LOW 중 대상 (기본 HIGH)
    - country: 국가 코드 필터 (선택)
    - limit: 1회 처리 이벤트 상한 (LLM 호출 수 제어)
    - force_refresh: 이미 분석이 있어도 다시 돌릴지 여부
    """

    days_back: int = Field(default=14, ge=0, le=365)
    days_forward: int = Field(default=14, ge=0, le=365)
    importance_levels: List[str] = Field(default_factory=lambda: ["HIGH"])
    country: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=200)
    force_refresh: bool = False
