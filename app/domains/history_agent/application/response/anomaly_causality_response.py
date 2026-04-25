from datetime import date
from typing import List

from pydantic import BaseModel

from app.domains.history_agent.application.response.timeline_response import HypothesisResult


class AnomalyCausalityResponse(BaseModel):
    """이상치 봉 1건의 causality(인과 가설) 응답.

    프론트에서 차트 ★ 마커 클릭 시 lazy-fetch 하여 팝업에 표시한다.
    - `hypotheses`: causality agent가 생성한 가설 목록 (빈 배열 가능).
    - `cached`: DB `event_enrichments` 캐시 히트 여부 — 관측·디버깅용.
    """

    ticker: str
    date: date
    hypotheses: List[HypothesisResult]
    cached: bool = False
