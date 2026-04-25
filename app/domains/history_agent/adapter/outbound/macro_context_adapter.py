"""RelatedAssetsClient + GprIndexClient 어댑터.

기존 causality_agent 외부 클라이언트를 감싸 history_agent 용 이벤트로 변환한다.
"""

import datetime
import logging
from typing import Dict, List, Optional

from app.domains.causality_agent.adapter.outbound.external.gpr_index_client import (
    GprIndexClient,
)
from app.domains.causality_agent.adapter.outbound.external.related_assets_client import (
    RelatedAssetsClient,
)
from app.domains.history_agent.application.port.out.related_assets_port import (
    GprIndexPort,
    MacroContextEvent,
    RelatedAssetsPort,
)

logger = logging.getLogger(__name__)


_SYMBOL_META: Dict[str, tuple[str, str, str]] = {
    # symbol → (event_type, korean_label_suffix, source_name)
    "^VIX": ("VIX_SPIKE", "VIX", "VIX"),
    "CL=F": ("OIL_SPIKE", "WTI 원유", "WTI"),
    "GC=F": ("GOLD_SPIKE", "금", "GOLD"),
    "^TNX": ("US10Y_SPIKE", "미국채 10Y", "UST10Y"),
    "JPY=X": ("FX_MOVE", "달러/엔", "JPYUSD"),
}


class RelatedAssetsAdapter(RelatedAssetsPort):
    def __init__(self, client: Optional[RelatedAssetsClient] = None):
        self._client = client or RelatedAssetsClient()

    async def fetch_significant_moves(
        self,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        threshold_pct: float,
    ) -> List[MacroContextEvent]:
        raw = await self._client.fetch(start_date=start_date, end_date=end_date)
        if not raw:
            return []
        events: List[MacroContextEvent] = []
        for asset in raw:
            symbol = asset.get("symbol", "")
            meta = _SYMBOL_META.get(symbol)
            if not meta:
                continue
            event_type, label_ko, source = meta
            bars = asset.get("bars") or []
            prev_close: Optional[float] = None
            prev_date: Optional[datetime.date] = None
            for bar in bars:
                try:
                    bar_date = datetime.date.fromisoformat(bar["date"])
                    close = float(bar["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if prev_close is not None and prev_close > 0:
                    pct = (close - prev_close) / prev_close * 100.0
                    if abs(pct) >= threshold_pct:
                        direction = "급등" if pct > 0 else "급락"
                        events.append(
                            MacroContextEvent(
                                date=bar_date,
                                type=event_type,  # type: ignore[arg-type]
                                label=f"{label_ko} {direction}",
                                detail=(
                                    f"{label_ko} {prev_close:.2f} → {close:.2f} "
                                    f"({pct:+.1f}%, D{(bar_date - prev_date).days})"
                                    if prev_date else
                                    f"{label_ko} {pct:+.1f}%"
                                ),
                                change_pct=round(pct, 2),
                                source=source,
                            )
                        )
                prev_close = close
                prev_date = bar_date
        return events


class GprIndexAdapter(GprIndexPort):
    def __init__(self, client: Optional[GprIndexClient] = None):
        self._client = client or GprIndexClient()

    async def fetch_mom_spikes(
        self,
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        mom_change_pct: float,
    ) -> List[MacroContextEvent]:
        raw = await self._client.fetch(start_date=start_date, end_date=end_date)
        if not raw:
            return []
        rows = []
        for row in raw:
            try:
                rows.append((datetime.date.fromisoformat(row["date"]), float(row["gpr"])))
            except (KeyError, TypeError, ValueError):
                continue
        rows.sort(key=lambda r: r[0])
        events: List[MacroContextEvent] = []
        prev_gpr: Optional[float] = None
        for row_date, gpr in rows:
            if prev_gpr is not None and prev_gpr > 0:
                pct = (gpr - prev_gpr) / prev_gpr * 100.0
                if pct >= mom_change_pct:
                    events.append(
                        MacroContextEvent(
                            date=row_date,
                            type="GEOPOLITICAL_RISK",
                            label="지정학 리스크 고조",
                            detail=(
                                f"GPR {prev_gpr:.1f} → {gpr:.1f} ({pct:+.1f}% MoM)"
                            ),
                            change_pct=round(pct, 2),
                            source="GPR",
                        )
                    )
            prev_gpr = gpr
        return events
