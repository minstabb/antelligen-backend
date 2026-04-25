from typing import Optional

from pydantic import BaseModel, Field


class SyncEconomicEventsRequest(BaseModel):
    """경제 일정 동기화 요청.

    - year 를 지정하면 해당 연도 ± 1년(총 3년) 범위를 조회한다.
    - year 미지정 시 현재 연도 기준으로 동일하게 계산.
    """

    year: Optional[int] = Field(default=None, description="기준 연도. 미지정 시 서버 현재 연도")
    years_back: int = Field(default=1, ge=0, le=5)
    years_forward: int = Field(default=1, ge=0, le=5)
