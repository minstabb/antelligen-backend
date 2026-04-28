"""FRED(Federal Reserve Economic Data) 기반 주요 경제 일정 조회 어댑터.

사용 엔드포인트:
- /fred/releases         : 릴리즈 메타(이름·press_release 플래그) 조회 → 중요도 산정에 사용
- /fred/release/dates    : 단일 릴리즈의 발표일 조회 (release_id 별로 호출)

FRED 의 모든 데이터는 미국(US) 기반이므로 country 를 'US' 로 고정한다.
press_release=True 인 릴리즈만 '주요 경제 일정' 으로 취급해 저장한다.

배경: FRED `/releases/dates` 는 realtime 윈도우(vintage 기간) 가 커질수록 결과집합이
(윈도우 × release 수) 로 폭증해 504/ReadTimeout 으로 실패한다. 대신 release_id 별로
`/release/dates` 를 병렬 호출하면 결과집합이 release 1개분(수백 row 이하)으로 작고
안정적이다. 실패한 release 는 skip 하고 다른 release 결과를 보존한다.
"""

import asyncio
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
RELEASE_DATES_URL = f"{FRED_BASE}/release/dates"

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

# FOMC 회의일에 동시 발표되는 release 들은 StaticCentralBankEventClient 의
# 'FOMC 기준금리 결정' entry 와 같은 날짜에 중복 노출돼 UI 가 지저분해진다.
# central_bank source 가 한글 타이틀로 회의 자체를 캐노니컬하게 다루므로
# 아래 키워드와 매칭되는 FRED release 는 수집 단계에서 제외한다.
#
# 제외 (회의 당일 중복):
#  - "FOMC Press Release"  : 회의 직후 성명서 (= central_bank entry 와 동일 날짜)
#  - "Federal Open Market Committee" / "Press Release: FOMC" : 위와 동의어 release 명 변형
#  - "Summary of Economic Projections" / "FOMC Projections Materials"
#                          : 분기 FOMC 당일 동시 공개 (점도표 등)
# 유지 (별도 날짜·정보):
#  - "Minutes of the Federal Open Market Committee" : 회의 3주 후 공개
#  - "Beige Book" : 회의 2주 전 공개
_FOMC_OVERLAP_KEYWORDS = (
    "fomc press release",
    "press release: fomc",
    "press release: federal open market committee",
    "federal open market committee press release",
    "summary of economic projections",
    "fomc projections materials",
)


class FredEconomicEventClient(EconomicEventFetchPort):
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 30.0,
        release_page_limit: int = 1000,   # FRED limit 최대 1000
        date_page_limit: int = 1000,      # FRED limit 최대 1000
        release_concurrency: int = 5,     # /release/dates 동시 호출 수 (FRED CDN throttle 회피)
        max_retries: int = 3,             # 5xx/403/네트워크 일시 장애 재시도 횟수
        retry_backoff_seconds: float = 1.5,
    ):
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._release_page_limit = release_page_limit
        self._date_page_limit = date_page_limit
        self._release_concurrency = release_concurrency
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_seconds

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
            target_ids: List[int] = []
            excluded_fomc: List[tuple[int, str]] = []
            excluded_low_importance = 0
            for rid, m in release_meta.items():
                if not m.get("press_release"):
                    continue
                name = m.get("name") or ""
                if self._is_fomc_overlap(name):
                    excluded_fomc.append((rid, name))
                    continue
                # US 일정 중 HIGH 가 아닌 release 는 영구 제외 (시장 영향이 작은
                # 부수 release 가 DB 에 누적돼 UI 노이즈가 되는 것을 차단).
                # HIGH 판정 = release 명이 _HIGH_IMPORTANCE_KEYWORDS 중 하나 포함.
                if self._classify_importance(name) != EventImportance.HIGH:
                    excluded_low_importance += 1
                    continue
                target_ids.append(rid)
            if excluded_fomc:
                print(
                    f"[schedule.fred.events] FOMC 중복 release 제외 {len(excluded_fomc)}건 "
                    f"(central_bank source 가 캐노니컬): "
                    f"{[(rid, name) for rid, name in excluded_fomc[:5]]}"
                    f"{'...' if len(excluded_fomc) > 5 else ''}"
                )
            if excluded_low_importance:
                print(
                    f"[schedule.fred.events] HIGH 미만 release 제외 {excluded_low_importance}건 "
                    f"(시장 영향 미미한 부수 release 영구 차단)"
                )
            print(
                f"[schedule.fred.events] 릴리즈 메타={len(release_meta)}건, "
                f"press_release 대상={len(target_ids)}건, 동시={self._release_concurrency}"
            )

            sem = asyncio.Semaphore(self._release_concurrency)
            failed: List[int] = []

            async def fetch_one(rid: int):
                async with sem:
                    try:
                        return rid, await self._fetch_dates_for_release(client, rid)
                    except Exception as exc:
                        logger.warning("[fred] release_id=%s 조회 실패: %s", rid, exc)
                        failed.append(rid)
                        return rid, []

            results = await asyncio.gather(*(fetch_one(rid) for rid in target_ids))

        if failed:
            print(f"[schedule.fred.events] 실패 release_id={len(failed)}건 (skip): {failed[:10]}{'...' if len(failed) > 10 else ''}")

        events: List[EconomicEvent] = []
        for rid, items in results:
            meta = release_meta.get(rid)
            if meta is None:
                continue
            for item in items:
                date_str = item.get("date")
                if not date_str:
                    continue
                try:
                    event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if event_date < start or event_date > end:
                    continue
                event_at = datetime.combine(event_date, time(0, 0), tzinfo=timezone.utc)
                name = meta.get("name") or f"Release {rid}"
                importance = self._classify_importance(name)
                events.append(
                    EconomicEvent(
                        source="fred",
                        source_event_id=f"release-{rid}-{date_str}",
                        title=name,
                        country="US",
                        event_at=event_at,
                        importance=importance,
                        description=(meta.get("notes") or "")[:900],
                        reference_url=meta.get("link"),
                    )
                )

        print(f"[schedule.fred.events] 기간 내 이벤트 = {len(events)}건")
        return events

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict, label: str
    ) -> httpx.Response:
        """5xx / 403(CDN throttle) / 네트워크 일시 장애에 대해 backoff 재시도."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    return response
                if response.status_code in (403, 429, 500, 502, 503, 504) and attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"FRED {label} 오류 status={response.status_code} "
                    f"body={response.text[:200]}"
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff * (attempt + 1))
                    continue
                raise RuntimeError(f"FRED {label} 네트워크 오류: {exc}") from exc
        raise RuntimeError(f"FRED {label} 재시도 한도 초과")  # pragma: no cover

    async def _fetch_release_metadata(self, client: httpx.AsyncClient) -> Dict[int, dict]:
        """/fred/releases 를 페이지네이션으로 전부 가져와 id → meta dict 로 반환."""
        result: Dict[int, dict] = {}
        offset = 0
        while True:
            response = await self._get_with_retry(
                client,
                RELEASES_URL,
                {
                    "api_key": self._api_key,
                    "file_type": "json",
                    "limit": str(self._release_page_limit),
                    "offset": str(offset),
                    "order_by": "release_id",
                    "sort_order": "asc",
                },
                "/releases",
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

    async def _fetch_dates_for_release(
        self, client: httpx.AsyncClient, release_id: int
    ) -> List[dict]:
        """단일 release 의 모든 발표일을 페이지네이션으로 조회.

        realtime 윈도우는 1900~9999 로 잡아 vintage 와 무관하게 release 의 전체
        date 이력을 받는다. 단일 release 라 결과집합이 작아(보통 수백 row 이내)
        timeout/504 가 발생하지 않는다.
        """
        result: List[dict] = []
        offset = 0
        while True:
            response = await self._get_with_retry(
                client,
                RELEASE_DATES_URL,
                {
                    "api_key": self._api_key,
                    "file_type": "json",
                    "release_id": str(release_id),
                    "realtime_start": "1900-01-01",
                    "realtime_end": "9999-12-31",
                    "include_release_dates_with_no_data": "true",
                    "limit": str(self._date_page_limit),
                    "offset": str(offset),
                    "order_by": "release_date",
                    "sort_order": "asc",
                },
                f"/release/dates rid={release_id}",
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

    @staticmethod
    def _is_fomc_overlap(name: str) -> bool:
        """release 명이 StaticCentralBankEventClient 의 FOMC entry 와 같은 날짜에
        중복 노출되는 항목인지 판정."""
        if not name:
            return False
        lowered = name.lower()
        return any(kw in lowered for kw in _FOMC_OVERLAP_KEYWORDS)
