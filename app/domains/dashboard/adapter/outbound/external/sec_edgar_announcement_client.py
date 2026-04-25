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

# Yahoo Finance 형태의 non-US ticker suffix 목록. SEC EDGAR는 US 상장 종목만 커버하므로
# 조기 반환해 불필요한 network I/O와 로그 노이즈("CIK 조회 실패") 제거 (S2-6).
# - KS/KQ: 한국 KOSPI/KOSDAQ
# - T: 일본 Tokyo, HK: 홍콩, SS/SZ: 상해/심천, L: 런던
# - PA: 파리, DE: 독일 Xetra, TO: 토론토, AX: 호주 ASX
_NON_US_TICKER_SUFFIXES = (
    ".KS", ".KQ", ".T", ".HK", ".SS", ".SZ", ".L", ".PA", ".DE", ".TO", ".AX",
)


def _is_non_us_ticker(ticker: str) -> bool:
    """Yahoo Finance 형식의 non-US ticker 판별.

    - `^` prefix: 지수 (^IXIC, ^GSPC, ^VIX, ^TNX, ...)
    - `.XX` suffix: 각 국가별 거래소
    """
    upper = ticker.upper()
    if upper.startswith("^"):
        return True
    return upper.endswith(_NON_US_TICKER_SUFFIXES)

# company_tickers.json은 약 10MB에 가까운 SEC 전역 공개 데이터.
# ticker별 조회마다 재다운로드하면 SEC에서 429(Too Many Requests)로 밴한다.
# 모듈 전역 한 번만 fetch하도록 single-flight 락 + 캐시.
_TICKERS_CACHE: dict[str, object] = {"data": None}
_TICKERS_LOCK = asyncio.Lock()
# 최근 SEC 429 응답 시각. 60s 이내 재요청은 short-circuit.
_SEC_429_BACKOFF_SECONDS = 60.0
_SEC_429_LAST_TS: dict[str, float] = {"ts": 0.0}

# SEC EDGAR fair-use 정책: 초당 10req. 동시성 5로 제한해 burst 방지.
# ETF holdings 병렬 fetch(SPY/QQQ 등) 시 ~30종목 × 5문서 = 150 요청이 동시에 발사되며
# 실측 결과 단일 초에 228건 429 수신됨. 전역 semaphore로 throttle.
# §17 S1-5: semaphore만으로는 round-trip이 빠를 때 burst 방지 불충분 → 각 요청 직후
# 최소 대기 간격을 추가. slot당 실효 rate = 1 / _SEC_MIN_INTERVAL ≈ 9 req/s.
_SEC_CONCURRENCY_LIMIT = 5
_SEC_MIN_INTERVAL = 0.11
_sec_semaphore: Optional[asyncio.Semaphore] = None


def _get_sec_semaphore() -> asyncio.Semaphore:
    """Lazy-init module-level semaphore. 이벤트 루프 바인딩 시점 지연."""
    global _sec_semaphore
    if _sec_semaphore is None:
        _sec_semaphore = asyncio.Semaphore(_SEC_CONCURRENCY_LIMIT)
    return _sec_semaphore


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
        # S2-6: non-US ticker는 SEC 커버리지 밖이므로 진입 단계에서 skip.
        # WARNING 로그도 남기지 않음 — 매 호출 반복되는 정상 시그널이므로 노이즈.
        if _is_non_us_ticker(ticker):
            return []
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

        # S2-6: non-US ticker는 SEC EDGAR 커버리지 밖이므로 조기 반환.
        # `^IXIC`/`.KS`/`.KQ` 등이 매 호출마다 company_tickers.json을 조회하며
        # 로그에 "CIK 조회 실패" 수백 건을 남기던 문제 해소.
        if _is_non_us_ticker(upper):
            return None

        if upper in _cik_cache:
            return _cik_cache[upper]

        data = await self._load_tickers_json()
        if data is None:
            return None

        for entry in data.values():
            if entry.get("ticker", "").upper() == upper:
                cik = str(entry["cik_str"]).zfill(10)
                _cik_cache[upper] = cik
                logger.info("[SecEdgar] CIK 조회 성공: %s → %s", ticker, cik)
                return cik

        return None

    async def _load_tickers_json(self) -> Optional[dict]:
        """company_tickers.json을 모듈 전역 1회만 다운로드한다.

        - 동시 요청은 single-flight lock으로 직렬화
        - SEC 429 수신 이후 60초는 short-circuit하여 추가 호출로 상황 악화 금지
        """
        if _TICKERS_CACHE["data"] is not None:
            return _TICKERS_CACHE["data"]  # type: ignore[return-value]

        now = asyncio.get_event_loop().time()
        if now - _SEC_429_LAST_TS["ts"] < _SEC_429_BACKOFF_SECONDS:
            logger.info("[SecEdgar] 최근 429 → tickers.json fetch short-circuit")
            return None

        async with _TICKERS_LOCK:
            if _TICKERS_CACHE["data"] is not None:
                return _TICKERS_CACHE["data"]  # type: ignore[return-value]
            try:
                async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": _USER_AGENT}) as client:
                    async with _get_sec_semaphore():
                        resp = await client.get(_TICKERS_URL)
                        await asyncio.sleep(_SEC_MIN_INTERVAL)
                if resp.status_code == 429:
                    _SEC_429_LAST_TS["ts"] = now
                    retry_after = resp.headers.get("Retry-After")
                    logger.warning(
                        "[SecEdgar] 429 수신 — 60s 동안 SEC 호출 우회. Retry-After=%s",
                        retry_after,
                    )
                    return None
                resp.raise_for_status()
                data = resp.json()
                _TICKERS_CACHE["data"] = data
                logger.info("[SecEdgar] tickers.json 로드: %d건", len(data))
                return data
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SecEdgar] tickers.json 로드 실패: %s", exc)
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
            async with _get_sec_semaphore():
                resp = await client.get(url, timeout=_DOC_FETCH_TIMEOUT)
                await asyncio.sleep(_SEC_MIN_INTERVAL)
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
            async with _get_sec_semaphore():
                resp = await client.get(_SUBMISSIONS_URL.format(cik=cik))
                await asyncio.sleep(_SEC_MIN_INTERVAL)
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
