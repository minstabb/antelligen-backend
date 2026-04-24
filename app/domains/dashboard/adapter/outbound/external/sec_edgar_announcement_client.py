import asyncio
import logging
import re
from datetime import date
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from app.domains.dashboard.application.port.out.sec_edgar_announcement_port import (
    SecEdgarAnnouncementPort,
)
from app.domains.dashboard.domain.entity.announcement_event import (
    AnnouncementEvent,
    AnnouncementEventType,
)

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FILING_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"
_USER_AGENT = "AntelliGen contact@antelligen.com"
_DOC_FETCH_TIMEOUT = 15.0
_BODY_MAX_CHARS = 600

# 대소문자 무시, Item X.XX 전체 탐색용 패턴
_ITEM_PATTERN = re.compile(r"(?i)\bitem\s+(\d+\.\d+)\b")

# 첨부파일 항목 — 본문 없음, 추출 대상 제외
_EXHIBIT_ITEMS = {"9.01", "9.02"}

# 8-K 아이템 코드 → 공시 타입
_ITEM_TYPE_MAP: list[tuple[str, AnnouncementEventType]] = [
    ("2.01", AnnouncementEventType.MERGER_ACQUISITION),
    ("1.01", AnnouncementEventType.CONTRACT),
    ("1.02", AnnouncementEventType.CONTRACT),
    ("8.01", AnnouncementEventType.MAJOR_EVENT),
    ("5.02", AnnouncementEventType.MAJOR_EVENT),
]

_TITLE_KEYWORD_MAP: list[tuple[str, AnnouncementEventType]] = [
    ("merger", AnnouncementEventType.MERGER_ACQUISITION),
    ("acquisition", AnnouncementEventType.MERGER_ACQUISITION),
    ("definitive agreement", AnnouncementEventType.MERGER_ACQUISITION),
    ("business combination", AnnouncementEventType.MERGER_ACQUISITION),
    ("agreement", AnnouncementEventType.CONTRACT),
    ("contract", AnnouncementEventType.CONTRACT),
    ("partnership", AnnouncementEventType.CONTRACT),
    ("mou", AnnouncementEventType.CONTRACT),
]

_cik_cache: dict[str, str] = {}


def _primary_item_code(items_str: str) -> str:
    """items_str(예: '5.02' 또는 '1.01, 9.01')에서 첨부파일 외 첫 번째 Item 코드를 반환한다."""
    codes = [c.strip() for c in items_str.split(",") if c.strip()]
    for code in codes:
        if code not in _EXHIBIT_ITEMS:
            return code
    return codes[0] if codes else ""


def _extract_item_body(html: str, target_item: str) -> str:
    """
    8-K HTML에서 target_item 섹션 본문을 추출한다.

    1. script·style·ix:header 제거 (table은 유지 — 본문이 table 안에 있는 경우 많음)
    2. 모든 'Item X.XX' 위치를 대소문자 무시로 탐색
    3. target_item 위치 ~ 다음 Item 위치 사이 슬라이싱
    4. target_item 매칭 없으면 첫 번째 Item 섹션 사용
    5. 결과를 _BODY_MAX_CHARS 이내로 제한
    """
    try:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "ix:header"]):
            tag.decompose()

        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()

        all_matches = list(_ITEM_PATTERN.finditer(text))
        if not all_matches:
            return ""

        # target_item에 해당하는 매칭 찾기
        target_match = next(
            (m for m in all_matches if m.group(1) == target_item),
            None,
        )

        # 매칭 없으면 첫 번째 Item 섹션 fallback
        if target_match is None:
            target_match = all_matches[0]

        start = target_match.start()

        # 다음 Item 위치 = 섹션 끝
        next_match = next((m for m in all_matches if m.start() > start), None)
        end = next_match.start() if next_match else len(text)

        section = text[start:end].strip()
        return section[:_BODY_MAX_CHARS]

    except Exception as exc:
        logger.debug("[SecEdgar] _extract_item_body 실패: %s", exc)
        return ""


def _classify_by_items(items_str: str) -> AnnouncementEventType:
    for item_code, event_type in _ITEM_TYPE_MAP:
        if item_code in items_str:
            return event_type
    return AnnouncementEventType.MAJOR_EVENT


def _classify_by_title(title: str) -> Optional[AnnouncementEventType]:
    lower = title.lower()
    for keyword, event_type in _TITLE_KEYWORD_MAP:
        if keyword in lower:
            return event_type
    return None


class SecEdgarAnnouncementClient(SecEdgarAnnouncementPort):

    async def fetch_announcements(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[AnnouncementEvent]:
        try:
            cik = await self._get_cik(ticker)
            if not cik:
                logger.warning("[SecEdgar] CIK 조회 실패: ticker=%s", ticker)
                return []
            return await self._fetch_8k_filings(cik, ticker, start_date, end_date)
        except Exception as e:
            logger.error("[SecEdgar] 오류 (ticker=%s): %s", ticker, e)
            return []

    async def _get_cik(self, ticker: str) -> Optional[str]:
        upper = ticker.upper()
        if upper in _cik_cache:
            return _cik_cache[upper]

        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(_TICKERS_URL)
            resp.raise_for_status()
            data = resp.json()

        for entry in data.values():
            if entry.get("ticker", "").upper() == upper:
                cik = str(entry["cik_str"]).zfill(10)
                _cik_cache[upper] = cik
                logger.info("[SecEdgar] CIK 조회 성공: %s → %s", ticker, cik)
                return cik

        return None

    async def _fetch_doc_body(
        self,
        client: httpx.AsyncClient,
        cik: str,
        accession_clean: str,
        primary_doc: str,
        items_str: str,
    ) -> str:
        """8-K 원문 HTML을 fetch해 대상 Item 섹션 텍스트를 반환한다. 실패 시 빈 문자열."""
        if not primary_doc:
            return ""
        url = _FILING_DOC_URL.format(
            cik=int(cik),
            accession=accession_clean,
            doc=primary_doc,
        )
        try:
            resp = await client.get(url, timeout=_DOC_FETCH_TIMEOUT)
            resp.raise_for_status()
            target_item = _primary_item_code(items_str)
            return _extract_item_body(resp.text, target_item)
        except Exception as exc:
            logger.debug("[SecEdgar] 문서 fetch 실패 (url=%s): %s", url, exc)
            return ""

    async def _fetch_8k_filings(
        self,
        cik: str,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[AnnouncementEvent]:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(_SUBMISSIONS_URL.format(cik=cik))
            resp.raise_for_status()
            data = resp.json()

            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            filing_dates = recent.get("filingDate", [])
            accession_numbers = recent.get("accessionNumber", [])
            items_list = recent.get("items", [])
            primary_docs = recent.get("primaryDocument", [])

            targets = []
            for i, form in enumerate(forms):
                if form != "8-K":
                    continue
                try:
                    filing_date = date.fromisoformat(filing_dates[i])
                except (ValueError, IndexError):
                    continue
                if not (start_date <= filing_date <= end_date):
                    continue
                targets.append(i)

            bodies = await asyncio.gather(
                *[
                    self._fetch_doc_body(
                        client,
                        cik,
                        accession_numbers[i].replace("-", ""),
                        primary_docs[i] if i < len(primary_docs) else "",
                        items_list[i] if i < len(items_list) else "",
                    )
                    for i in targets
                ],
                return_exceptions=True,
            )

        events: List[AnnouncementEvent] = []
        for idx, i in enumerate(targets):
            items_str = items_list[i] if i < len(items_list) else ""
            accession = accession_numbers[i] if i < len(accession_numbers) else ""
            primary_doc = primary_docs[i] if i < len(primary_docs) else ""
            filing_date = date.fromisoformat(filing_dates[i])

            accession_clean = accession.replace("-", "")
            filing_url = _FILING_DOC_URL.format(
                cik=int(cik),
                accession=accession_clean,
                doc=primary_doc,
            ) if primary_doc else (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={int(cik)}&type=8-K"
            )

            event_type = _classify_by_items(items_str)
            title_hint = _classify_by_title(primary_doc)
            if title_hint and event_type == AnnouncementEventType.MAJOR_EVENT:
                event_type = title_hint

            body = bodies[idx] if not isinstance(bodies[idx], Exception) else ""
            title = body if body else (f"8-K [{items_str}]" if items_str else "8-K Filing")

            events.append(AnnouncementEvent(
                date=filing_date,
                type=event_type,
                title=title,
                source="sec_edgar",
                url=filing_url,
            ))

        logger.info("[SecEdgar] ticker=%s, CIK=%s, 8-K 수집=%d건", ticker, cik, len(events))
        return events
