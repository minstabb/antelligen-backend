import logging
from datetime import date
from typing import List, Optional

import httpx

from app.domains.dashboard.domain.entity.corporate_event import CorporateEvent, CorporateEventType
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# (키워드, 이벤트 타입) — 앞에 있을수록 우선 매칭
_KEYWORD_MAP: list[tuple[str, CorporateEventType]] = [
    ("자기주식소각", CorporateEventType.BUYBACK_CANCEL),
    ("자기주식취득", CorporateEventType.BUYBACK),
    ("자기주식 소각", CorporateEventType.BUYBACK_CANCEL),
    ("자기주식 취득", CorporateEventType.BUYBACK),
    ("자기주식", CorporateEventType.BUYBACK),
    ("유상증자", CorporateEventType.RIGHTS_OFFERING),
    ("현금배당", CorporateEventType.DIVIDEND),
    ("주식배당", CorporateEventType.DIVIDEND),
    ("배당", CorporateEventType.DIVIDEND),
    ("임원ㆍ주요주주", CorporateEventType.MANAGEMENT_CHANGE),
    ("임원·주요주주", CorporateEventType.MANAGEMENT_CHANGE),
    ("임원변동", CorporateEventType.MANAGEMENT_CHANGE),
    ("임원", CorporateEventType.MANAGEMENT_CHANGE),
    ("사업보고서", CorporateEventType.EARNINGS),
    ("분기보고서", CorporateEventType.EARNINGS),
    ("반기보고서", CorporateEventType.EARNINGS),
]


def _classify(report_nm: str) -> CorporateEventType:
    for keyword, event_type in _KEYWORD_MAP:
        if keyword in report_nm:
            return event_type
    return CorporateEventType.DISCLOSURE


def _parse_date(rcept_dt: str) -> Optional[date]:
    try:
        return date(int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))
    except Exception:
        return None


class DartCorporateEventClient:
    """DART OpenAPI에서 기업 공시 이벤트를 수집하는 어댑터."""

    async def fetch_corporate_events(
        self,
        corp_code: str,
        start_date: date,
        end_date: date,
    ) -> List[CorporateEvent]:
        bgn_de = start_date.strftime("%Y%m%d")
        end_de = end_date.strftime("%Y%m%d")

        try:
            disclosures = await self._fetch_all_pages(corp_code, bgn_de, end_de)
        except Exception as e:
            logger.error("[DartCorporateEvent] 조회 실패 (corp_code=%s): %s", corp_code, e)
            return []

        events: List[CorporateEvent] = []
        for d in disclosures:
            event_date = _parse_date(d.get("rcept_dt", ""))
            if event_date is None:
                continue
            report_nm = d.get("report_nm", "")
            events.append(CorporateEvent(
                date=event_date,
                type=_classify(report_nm),
                detail=report_nm,
                source="dart",
            ))

        logger.info(
            "[DartCorporateEvent] corp_code=%s, 기간=%s~%s, 수집=%d건",
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
                    "page_no": page_no,
                    "page_count": 100,
                }
                response = await client.get(DART_LIST_URL, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("status") in ("013", "020"):
                    break
                if data.get("status") != "000":
                    logger.warning("DART API 상태 오류: %s", data.get("message"))
                    break

                items = data.get("list", [])
                all_items.extend(items)

                total_page = int(data.get("total_page", 0))
                if page_no >= total_page or not items:
                    break
                page_no += 1

        return all_items
