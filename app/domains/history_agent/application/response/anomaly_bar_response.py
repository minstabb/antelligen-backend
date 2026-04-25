from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class AnomalyBarResponse(BaseModel):
    """차트에 ★ 마커로 표시할 이상치 봉 1건.

    - `return_pct`: 해당 봉의 종가 수익률(%) — 직전 봉 대비 (%p 아님).
    - `z_score`: `(return_pct/100 - μ) / σ` — 봉 단위별 rolling window 기준.
    - `direction`: `"up"` | `"down"` — 프론트 색 구분에 사용.
    - `causality`: 초기엔 null. 마커 클릭 시 `/anomaly-bars/{ticker}/{date}/causality`
      엔드포인트가 lazy-fetch 한다.
    """
    date: date
    return_pct: float
    z_score: float
    direction: str
    close: float
    causality: Optional[str] = None


class AnomalyBarsResponse(BaseModel):
    ticker: str
    chart_interval: str
    count: int
    events: List[AnomalyBarResponse]
