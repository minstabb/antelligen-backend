"""DART OpenAPI 기반 기업 잠정실적 발표일 수집/추정 클라이언트.

전략:
- 각 기업의 과거 영업(잠정)실적(공정공시)을 DART에서 조회 → 실제 발표일 추출
- 미래 분기는 기업별 분기별 historical median delta로 추정
- 모든 발표일은 한국 영업일(주말·공휴일 제외)로 보정
"""

from __future__ import annotations

import asyncio
import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from app.domains.schedule.adapter.outbound.external.dart_corp_companies import (
    COMPANIES,
    EARLY_PRIORITY_TICKERS,
    CorpMeta,
)
from app.domains.schedule.application.port.out.economic_event_fetch_port import (
    EconomicEventFetchPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.domain.service.korean_business_day import (
    shift_to_previous_business_day,
)
from app.domains.schedule.domain.value_object.event_importance import EventImportance

logger = logging.getLogger(__name__)

SOURCE_NAME = "corp_earnings"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

QUARTER_END: Dict[str, Tuple[int, int]] = {
    "Q1": (3, 31),
    "Q2": (6, 30),
    "Q3": (9, 30),
    "Q4": (12, 31),
}

# historical 데이터가 없을 때 fallback 으로 사용하는 분기말 D+N일 추정치
DEFAULT_DELTA_DAYS: Dict[str, int] = {"Q1": 30, "Q2": 30, "Q3": 30, "Q4": 60}

# 분기 캐노니컬 발표 (연결재무제표 기준) — 대다수 대형주가 채택
CONSOLIDATED_PATTERN = "연결재무제표기준영업(잠정)실적"
# 단일(연결 미보고) 잠정실적 — 소형주 fallback. 단, 자동차/유통 등은 매월 1일에
# 월간 판매·생산 실적도 동일 표제로 공시하므로 분기말 D+N일 윈도우로 필터.
PLAIN_PATTERN = "영업(잠정)실적"
PLAIN_FILING_WINDOW = (5, 65)  # 분기말로부터 [min, max]일

# 제외 패턴: 정정공시 / 발표 예고 / 자회사 동시 공시
EXCLUSION_SUBSTRINGS: Tuple[str, ...] = (
    "[기재정정]",
    "결산실적공시예고",
    "(자회사의",
)


@dataclass(frozen=True)
class _Filing:
    """과거 1건의 잠정실적 공시 기록."""

    report_year: int   # 보고 대상 연도 (예: 2026-01-25 공시 → Q4 2025 → 2025)
    quarter: str       # "Q1" ~ "Q4"
    filed_date: date   # 실제 공시(접수)일
    is_consolidated: bool  # 연결재무제표기준 여부 (canonical quarterly 표시)


def _infer_quarter(filed: date) -> Tuple[int, str]:
    """공시 접수일로부터 (보고연도, 분기) 추정.

    - 1~3월 공시 → 전년도 Q4
    - 4~6월 → 당해 Q1
    - 7~9월 → 당해 Q2
    - 10~12월 → 당해 Q3
    """
    m = filed.month
    if m <= 3:
        return filed.year - 1, "Q4"
    if m <= 6:
        return filed.year, "Q1"
    if m <= 9:
        return filed.year, "Q2"
    return filed.year, "Q3"


def _classify_filing(
    report_nm: str, filed: date,
) -> Optional[Tuple[int, str, bool]]:
    """공시 항목을 잠정실적 캐노니컬 발표로 분류.

    반환: (report_year, quarter, is_consolidated) 또는 None (제외 대상)
    """
    if any(s in report_nm for s in EXCLUSION_SUBSTRINGS):
        return None

    is_consolidated = CONSOLIDATED_PATTERN in report_nm
    is_plain = (not is_consolidated) and (PLAIN_PATTERN in report_nm)
    if not (is_consolidated or is_plain):
        return None

    ry, q = _infer_quarter(filed)

    # 단일(plain) 발표는 월간 매출 보고서와 혼재 가능 → 분기말 윈도우로 필터.
    if is_plain:
        qe_m, qe_d = QUARTER_END[q]
        delta = (filed - date(ry, qe_m, qe_d)).days
        if not (PLAIN_FILING_WINDOW[0] <= delta <= PLAIN_FILING_WINDOW[1]):
            return None

    return ry, q, is_consolidated


def _select_actual_filing(filings: List[_Filing]) -> Optional[date]:
    """동일 (연도, 분기) 버킷 내에서 캐노니컬 발표일 선정.

    - 연결재무제표 발표가 있으면 그 중 최초(1차 발표)를 선정
    - 없으면 단일 발표 중 최초
    """
    consolidated = [f for f in filings if f.is_consolidated]
    if consolidated:
        return min(f.filed_date for f in consolidated)
    if filings:
        return min(f.filed_date for f in filings)
    return None


def _project_filing_date(
    history: List[_Filing], target_year: int, quarter: str,
) -> date:
    """기업의 quarter별 historical median delta 로 target_year 발표일 추정.

    동일 (연도, 분기) 의 여러 공시 중 캐노니컬 1건만 골라 패턴 학습에 사용.
    """
    qe_month, qe_day = QUARTER_END[quarter]
    target_qe = date(target_year, qe_month, qe_day)

    # (year, quarter) → 캐노니컬 발표일 인덱스 (분기당 1건)
    canonical: Dict[Tuple[int, str], date] = {}
    for f in history:
        if f.quarter != quarter:
            continue
        key = (f.report_year, f.quarter)
        canonical.setdefault(key, _select_actual_filing(
            [g for g in history if g.report_year == f.report_year and g.quarter == quarter]
        ))

    if canonical:
        deltas = sorted(
            (d - date(yr, qe_month, qe_day)).days
            for (yr, _), d in canonical.items() if d is not None
        )
        if deltas:
            median = deltas[len(deltas) // 2]
            return target_qe + timedelta(days=median)

    return target_qe + timedelta(days=DEFAULT_DELTA_DAYS[quarter])


class DartCorpEarningsClient(EconomicEventFetchPort):
    """DART OpenAPI를 이용한 기업 잠정실적 발표일 수집기.

    - lookback_years 기간의 과거 잠정실적 공시를 수집해 실제 발표일을 정확히 반영
    - 해당 분기의 공시가 아직 없으면 historical median delta 로 추정
    - 모든 발표일은 한국 영업일로 보정 (주말/공휴일 → 직전 영업일)
    - DART API 호출은 기업별 동시 N개로 throttling
    """

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 30.0,
        lookback_years: int = 3,
        concurrency: int = 8,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._lookback_years = lookback_years
        self._semaphore = asyncio.Semaphore(concurrency)
        self._corp_code_map: Optional[Dict[str, str]] = None
        self._init_lock = asyncio.Lock()

    async def fetch(self, start: date, end: date) -> List[EconomicEvent]:
        if not self._api_key:
            logger.warning(
                "[corp_earnings.dart] OPEN_DART_API_KEY 미설정 — 빈 결과 반환"
            )
            return []

        try:
            await self._ensure_corp_code_map()
        except Exception as exc:
            logger.error("[corp_earnings.dart] corpCode.xml 다운로드 실패: %s", exc)
            return []

        target_years = sorted(set(range(start.year, end.year + 1)))
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            results = await asyncio.gather(
                *[
                    self._build_company_events(http, corp, target_years)
                    for corp in COMPANIES
                ],
                return_exceptions=True,
            )

        events: List[EconomicEvent] = []
        for corp, r in zip(COMPANIES, results):
            if isinstance(r, BaseException):
                logger.warning(
                    "[corp_earnings.dart] 기업 처리 실패 ticker=%s: %s",
                    corp.ticker, r,
                )
                continue
            events.extend(r)

        in_range = [e for e in events if start <= e.event_at.date() <= end]
        logger.info(
            "[corp_earnings.dart] 수집 완료 total=%d in_range=%d (start=%s end=%s)",
            len(events), len(in_range), start, end,
        )
        return in_range

    async def _build_company_events(
        self,
        http: httpx.AsyncClient,
        corp: CorpMeta,
        target_years: List[int],
    ) -> List[EconomicEvent]:
        assert self._corp_code_map is not None  # _ensure_corp_code_map 선행 보장
        corp_code = self._corp_code_map.get(corp.ticker)
        if not corp_code:
            logger.debug(
                "[corp_earnings.dart] DART corp_code 미발견 ticker=%s name=%s",
                corp.ticker, corp.name,
            )
            return []

        async with self._semaphore:
            history = await self._fetch_history(http, corp_code)

        # 보고연도-분기별 캐노니컬 발표일 인덱스
        # 동일 (연도, 분기) 의 여러 공시 중 1건만 선정 (연결재무제표 우선, 최초 발표 우선)
        bucketed: Dict[Tuple[int, str], List[_Filing]] = {}
        for f in history:
            bucketed.setdefault((f.report_year, f.quarter), []).append(f)
        actual: Dict[Tuple[int, str], date] = {}
        for key, filings in bucketed.items():
            picked = _select_actual_filing(filings)
            if picked is not None:
                actual[key] = picked

        events: List[EconomicEvent] = []
        for year in target_years:
            for q in ("Q1", "Q2", "Q3", "Q4"):
                key = (year, q)
                if key in actual:
                    raw_date = actual[key]
                    is_actual = True
                else:
                    raw_date = _project_filing_date(history, year, q)
                    is_actual = False

                adjusted = shift_to_previous_business_day(raw_date)
                events.append(self._to_event(corp, year, q, adjusted, is_actual))

        return events

    @staticmethod
    def _to_event(
        corp: CorpMeta,
        year: int,
        quarter: str,
        event_date: date,
        is_actual: bool,
    ) -> EconomicEvent:
        event_at = datetime.combine(event_date, time(0, 0), tzinfo=timezone.utc)
        is_priority = corp.ticker in EARLY_PRIORITY_TICKERS
        importance = (
            EventImportance.MEDIUM if is_priority else EventImportance.LOW
        )
        status_prefix = "[확정] " if is_actual else "[예정] "
        priority_prefix = "[선공시] " if is_priority else ""
        kind = "공시 확정" if is_actual else "패턴 기반 추정"
        idx_label = ", ".join(corp.indices) if corp.indices else ""
        idx_desc = f" 소속 지수: {idx_label}." if idx_label else ""

        return EconomicEvent(
            source=SOURCE_NAME,
            source_event_id=f"{corp.ticker}-{year}-{quarter}",
            title=(
                f"{status_prefix}{priority_prefix}{corp.name}({corp.ticker}) "
                f"{quarter} 잠정실적 발표"
            ),
            country="KR",
            event_at=event_at,
            importance=importance,
            description=(
                f"{corp.market} 상장사 {corp.name}({corp.ticker})의 {year}년 "
                f"{quarter} 잠정실적 발표일 ({kind}, 영업일 보정 적용).{idx_desc} "
                f"분석 파이프라인 제외, 일정 표시용."
            ),
            reference_url=None,
        )

    async def _fetch_history(
        self,
        http: httpx.AsyncClient,
        corp_code: str,
    ) -> List[_Filing]:
        end_date = date.today()
        start_date = date(end_date.year - self._lookback_years, 1, 1)
        bgn_de = start_date.strftime("%Y%m%d")
        end_de = end_date.strftime("%Y%m%d")

        all_items: List[dict] = []
        page_no = 1
        while True:
            try:
                resp = await http.get(
                    LIST_URL,
                    params={
                        "crtfc_key": self._api_key,
                        "corp_code": corp_code,
                        "bgn_de": bgn_de,
                        "end_de": end_de,
                        "pblntf_ty": "I",  # 거래소공시
                        "page_no": page_no,
                        "page_count": 100,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning(
                    "[corp_earnings.dart] list.json 호출 실패 corp=%s page=%d: %s",
                    corp_code, page_no, exc,
                )
                break

            status = data.get("status")
            if status in ("013", "020"):  # 자료 없음 / API 한도 초과
                break
            if status != "000":
                logger.warning(
                    "[corp_earnings.dart] DART 응답 비정상 corp=%s status=%s msg=%s",
                    corp_code, status, data.get("message"),
                )
                break

            items = data.get("list") or []
            all_items.extend(items)
            total_page = int(data.get("total_page", 0))
            if page_no >= total_page or not items:
                break
            page_no += 1

        filings: List[_Filing] = []
        for item in all_items:
            report_nm = (item.get("report_nm", "") or "").strip()
            rcept_dt = item.get("rcept_dt", "") or ""
            try:
                filed = date(
                    int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8])
                )
            except (ValueError, IndexError):
                continue
            classified = _classify_filing(report_nm, filed)
            if classified is None:
                continue
            ry, q, is_consol = classified
            filings.append(
                _Filing(
                    report_year=ry,
                    quarter=q,
                    filed_date=filed,
                    is_consolidated=is_consol,
                )
            )
        return filings

    async def _ensure_corp_code_map(self) -> None:
        if self._corp_code_map is not None:
            return
        async with self._init_lock:
            if self._corp_code_map is not None:
                return
            self._corp_code_map = await self._download_corp_code_map()

    async def _download_corp_code_map(self) -> Dict[str, str]:
        """DART corpCode.xml 을 다운로드해 stock_code → corp_code 매핑 구성."""
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.get(
                CORP_CODE_URL, params={"crtfc_key": self._api_key}
            )
            resp.raise_for_status()
        mapping: Dict[str, str] = {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_filename = zf.namelist()[0]
            with zf.open(xml_filename) as xml_file:
                tree = ET.parse(xml_file)
                for item in tree.getroot().findall("list"):
                    stock_code = (item.findtext("stock_code", "") or "").strip()
                    corp_code = (item.findtext("corp_code", "") or "").strip()
                    if stock_code and corp_code:
                        mapping[stock_code] = corp_code
        logger.info(
            "[corp_earnings.dart] DART corp_code 매핑 로드 완료 (count=%d)",
            len(mapping),
        )
        return mapping
