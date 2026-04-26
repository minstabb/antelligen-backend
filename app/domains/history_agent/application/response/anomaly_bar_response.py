from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class AnomalyBarResponse(BaseModel):
    """차트에 ★ 마커로 표시할 이상치 봉 1건.

    - `return_pct`: 해당 봉의 종가 수익률(%) — 직전 봉 대비 (%p 아님).
    - `z_score`: `(return_pct/100 - μ) / σ` — 봉 단위별 rolling window 기준.
    - `direction`: `"up"` | `"down"` — 프론트 색 구분에 사용.
    - `volume_ratio`: 같은 σ window 평균 거래량 대비 배수. 평균이 0/누락이면 None.
    - `time_of_day`: 일봉(1D)에서만 채워지는 갭/장중 근사 — "GAP" | "INTRADAY".
      |open-prev_close| > |close-open| 이면 GAP. 분봉 미수집 환경의 best-effort 근사.
      일봉 외(주/월/분기봉) 또는 prev close 부재 시 None.
    - `causality`: 초기엔 null. 마커 클릭 시 `/anomaly-bars/{ticker}/{date}/causality`
      엔드포인트가 lazy-fetch 한다.
    """
    date: date
    return_pct: float
    z_score: float
    direction: str
    close: float
    volume_ratio: Optional[float] = None
    time_of_day: Optional[str] = None
    causality: Optional[str] = None


class AnomalyBarsResponse(BaseModel):
    ticker: str
    chart_interval: str
    count: int
    events: List[AnomalyBarResponse]
