import json
import logging
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from app.domains.history_agent.application.port.out.curated_macro_events_port import (
    CuratedMacroEventsPort,
)
from app.domains.history_agent.domain.entity.curated_macro_event import CuratedMacroEvent

logger = logging.getLogger(__name__)

_DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "seed"
    / "historic_macro_events.json"
)


@lru_cache(maxsize=4)
def _load_catalog(seed_path_str: str) -> List[CuratedMacroEvent]:
    path = Path(seed_path_str)
    if not path.exists():
        logger.warning("[CuratedMacroEvents] seed 파일 없음: %s", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("[CuratedMacroEvents] seed 파싱 실패: %s (%s)", path, exc)
        return []
    events: List[CuratedMacroEvent] = []
    for item in raw:
        try:
            events.append(
                CuratedMacroEvent(
                    date=datetime.strptime(item["date"], "%Y-%m-%d").date(),
                    event_type=item["event_type"],
                    region=item["region"].upper(),
                    title=item["title"],
                    detail=item["detail"],
                    tags=list(item.get("tags", [])),
                    importance_score=float(item.get("importance_score", 1.0)),
                    source_url=item.get("source_url"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("[CuratedMacroEvents] 항목 스킵: %s (%s)", item, exc)
    logger.info("[CuratedMacroEvents] seed 로드 완료: %d건 (%s)", len(events), path.name)
    return events


class CuratedMacroEventsAdapter(CuratedMacroEventsPort):

    def __init__(self, seed_path: Optional[Path] = None):
        self._seed_path = Path(seed_path) if seed_path else _DEFAULT_SEED_PATH

    async def fetch(
        self,
        *,
        region: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[CuratedMacroEvent]:
        catalog = _load_catalog(str(self._seed_path))
        if not catalog:
            return []

        region_upper = region.upper()
        if region_upper == "GLOBAL":
            allowed = None
        else:
            allowed = {region_upper, "GLOBAL"}

        filtered: List[CuratedMacroEvent] = []
        for event in catalog:
            if start_date is not None and event.date < start_date:
                continue
            if end_date is not None and event.date > end_date:
                continue
            if allowed is not None and event.region not in allowed:
                continue
            filtered.append(event)
        filtered.sort(key=lambda e: e.date, reverse=True)
        return filtered
