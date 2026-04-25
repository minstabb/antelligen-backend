"""FRED(Federal Reserve Economic Data) 기반 주요 경제 일정 조회 어댑터.

사용 엔드포인트:
- /fred/releases         : 릴리즈 메타(이름·press_release 플래그) 조회 → 중요도 산정에 사용
- /fred/releases/dates   : 기간 내 릴리즈 발표 날짜 조회

FRED 의 모든 데이터는 미국(US) 기반이므로 country 를 'US' 로 고정한다.
press_release=True 인 릴리즈만 '주요 경제 일정' 으로 취급해 저장한다.
"""

import logging
from datetime import date, datetime, time, timezone
from typing import Dict, List

import httpx

from app.domains.schedule.application.port.out.economic_event_fetch_port import (
    EconomicEventFetchPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.domain.value_object.event_importance import EventImportance

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
RELEASES_URL = f"{FRED_BASE}/releases"
RELEASE_DATES_URL = f"{FRED_BASE}/releases/dates"

# press_release=True 중에서도 시장 반응이 큰 대표 릴리즈 이름 키워드 → HIGH 로 승격
_HIGH_IMPORTANCE_KEYWORDS = (
    "Consumer Price Index",     # CPI
    "Producer Price Index",     # PPI
    "Employment Situation",     # Nonfarm Payrolls
    "Gross Domestic Product",   # GDP
    "Personal Income and Outlays",  # PCE
    "Retail Trade",
    "Advance Monthly Sales for Retail",
    "FOMC",
    "ISM",
    "Industrial Production",
)


class FredEconomicEventClient(EconomicEventFetchPort):
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 15.0,
        release_page_limit: int = 1000,   # FRED limit 최대 1000
        date_page_limit: int = 1000,      # FRED limit 최대 1000
    ):
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._release_page_limit = release_page_limit
        self._date_page_limit = date_page_limit

    async def fetch(self, start: date, end: date) -> List[EconomicEvent]:
        if not self._api_key:
            raise RuntimeError("FRED_API_KEY 가 설정되지 않았습니다.")
        if end < start:
            raise ValueError("end 는 start 이후여야 합니다.")

        print(
            f"[schedule.fred.events] 요청 start={start.isoformat()} end={end.isoformat()}"
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            release_meta = await self._fetch_release_metadata(client)
            raw_dates = await self._fetch_release_dates(client, start, end)

        print(
            f"[schedule.fred.events] 릴리즈 메타={len(release_meta)}건, "
            f"기간 내 이벤트={len(raw_dates)}건"
        )

        events: List[EconomicEvent] = []
        for item in raw_dates:
            release_id = item.get("release_id")
            date_str = item.get("date")
            if release_id is None or not date_str:
                continue
            meta = release_meta.get(release_id)
            if meta is None:
                continue
            if not meta.get("press_release"):
                # press_release=False → 주요 일정 아님. 스킵.
                continue

            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            event_at = datetime.combine(event_date, time(0, 0), tzinfo=timezone.utc)

            name = meta.get("name") or item.get("release_name") or f"Release {release_id}"
            importance = self._classify_importance(name)

            events.append(
                EconomicEvent(
                    source="fred",
                    source_event_id=f"release-{release_id}-{date_str}",
                    title=name,
                    country="US",
                    event_at=event_at,
                    importance=importance,
                    description=(meta.get("notes") or "")[:900],
                    reference_url=meta.get("link"),
                )
            )

        print(f"[schedule.fred.events] 주요(press_release) 이벤트 = {len(events)}건")
        return events

    async def _fetch_release_metadata(self, client: httpx.AsyncClient) -> Dict[int, dict]:
        """/fred/releases 를 페이지네이션으로 전부 가져와 id → meta dict 로 반환."""
        result: Dict[int, dict] = {}
        offset = 0
        while True:
            response = await client.get(
                RELEASES_URL,
                params={
                    "api_key": self._api_key,
                    "file_type": "json",
                    "limit": str(self._release_page_limit),
                    "offset": str(offset),
                    "order_by": "release_id",
                    "sort_order": "asc",
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"FRED /releases 오류 status={response.status_code} "
                    f"body={response.text[:200]}"
                )
            data = response.json()
            releases = data.get("releases") or []
            for r in releases:
                rid = r.get("id")
                if rid is None:
                    continue
                result[rid] = {
                    "name": r.get("name"),
                    "press_release": bool(r.get("press_release")),
                    "link": r.get("link"),
                    "notes": r.get("notes"),
                }
            count = int(data.get("count") or 0)
            offset += len(releases)
            if offset >= count or not releases:
                break
        return result

    async def _fetch_release_dates(
        self, client: httpx.AsyncClient, start: date, end: date
    ) -> List[dict]:
        """/fred/releases/dates 를 페이지네이션으로 전부 가져온다."""
        result: List[dict] = []
        offset = 0
        while True:
            response = await client.get(
                RELEASE_DATES_URL,
                params={
                    "api_key": self._api_key,
                    "file_type": "json",
                    "realtime_start": start.isoformat(),
                    "realtime_end": end.isoformat(),
                    "include_release_dates_with_no_data": "true",
                    "limit": str(self._date_page_limit),
                    "offset": str(offset),
                    "order_by": "release_date",
                    "sort_order": "asc",
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"FRED /releases/dates 오류 status={response.status_code} "
                    f"body={response.text[:200]}"
                )
            data = response.json()
            items = data.get("release_dates") or []
            result.extend(items)
            count = int(data.get("count") or 0)
            offset += len(items)
            if offset >= count or not items:
                break
        return result

    @staticmethod
    def _classify_importance(name: str) -> EventImportance:
        if not name:
            return EventImportance.MEDIUM
        lowered = name.lower()
        for kw in _HIGH_IMPORTANCE_KEYWORDS:
            if kw.lower() in lowered:
                return EventImportance.HIGH
        return EventImportance.MEDIUM
