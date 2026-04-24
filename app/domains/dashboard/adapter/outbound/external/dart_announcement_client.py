import logging
from datetime import date
from typing import List, Optional

import httpx

from app.domains.dashboard.domain.entity.announcement_event import (
    AnnouncementEvent,
    AnnouncementEventType,
)
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_FILING_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

# 주요사항보고서 공시 타입 코드
_PBLNTF_TY_MAJOR = "B"

# 공시명 키워드 → 공시 타입 (우선순위 순)
_KEYWORD_MAP: list[tuple[str, AnnouncementEventType]] = [
    ("합병", AnnouncementEventType.MERGER_ACQUISITION),
    ("인수", AnnouncementEventType.MERGER_ACQUISITION),
    ("영업양수", AnnouncementEventType.MERGER_ACQUISITION),
    ("영업양도", AnnouncementEventType.MERGER_ACQUISITION),
    ("주식교환", AnnouncementEventType.MERGER_ACQUISITION),
    ("주식이전", AnnouncementEventType.MERGER_ACQUISITION),
    ("분할합병", AnnouncementEventType.MERGER_ACQUISITION),
    ("업무협약", AnnouncementEventType.CONTRACT),
    ("MOU", AnnouncementEventType.CONTRACT),
    ("계약", AnnouncementEventType.CONTRACT),
    ("분할", AnnouncementEventType.MAJOR_EVENT),
    ("주요사항", AnnouncementEventType.MAJOR_EVENT),
]


def _classify(report_nm: str) -> AnnouncementEventType:
    for keyword, event_type in _KEYWORD_MAP:
        if keyword in report_nm:
            return event_type
    return AnnouncementEventType.MAJOR_EVENT


def _parse_date(rcept_dt: str) -> Optional[date]:
    try:
        return date(int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))
    except Exception:
        return None


class DartAnnouncementClient:
    """DART OpenAPI에서 주요사항보고서를 수집하는 어댑터."""

    async def fetch_announcements(
        self,
        corp_code: str,
        start_date: date,
        end_date: date,
    ) -> List[AnnouncementEvent]:
        bgn_de = start_date.strftime("%Y%m%d")
        end_de = end_date.strftime("%Y%m%d")
        try:
            disclosures = await self._fetch_all_pages(corp_code, bgn_de, end_de)
        except Exception as e:
            logger.error("[DartAnnouncement] 조회 실패 (corp_code=%s): %s", corp_code, e)
            return []

        events: List[AnnouncementEvent] = []
        for d in disclosures:
            event_date = _parse_date(d.get("rcept_dt", ""))
            if event_date is None:
                continue
            report_nm = d.get("report_nm", "")
            rcept_no = d.get("rcept_no", "")
            events.append(AnnouncementEvent(
                date=event_date,
                type=_classify(report_nm),
                title=report_nm,
                source="dart",
                url=DART_FILING_URL.format(rcept_no=rcept_no),
            ))

        logger.info(
            "[DartAnnouncement] corp_code=%s, 기간=%s~%s, 수집=%d건",
            corp_code, bgn_de, end_de, len(events),
        )
        return events

    async def _fetch_all_pages(
        self,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> list[dict]:
        settings = get_settings()
        all_items: list[dict] = []
        page_no = 1

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                params = {
                    "crtfc_key": settings.open_dart_api_key,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "pblntf_ty": _PBLNTF_TY_MAJOR,
                    "page_no": page_no,
                    "page_count": 100,
                }
                response = await client.get(DART_LIST_URL, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("status") in ("013", "020"):
                    break
                if data.get("status") != "000":
                    logger.warning("[DartAnnouncement] API 상태 오류: %s", data.get("message"))
                    break

                items = data.get("list", [])
                all_items.extend(items)

                total_page = int(data.get("total_page", 0))
                if page_no >= total_page or not items:
                    break
                page_no += 1

        return all_items
