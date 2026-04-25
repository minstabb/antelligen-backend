import asyncio
import logging
import time
from typing import Optional

import httpx

from app.domains.disclosure.application.port.foreign_disclosure_api_port import ForeignDisclosureApiPort
from app.domains.disclosure.domain.entity.foreign_filing import ForeignFiling

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FILING_VIEWER_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"

_DEFAULT_FORM_TYPES = ["8-K", "10-K", "10-Q"]
_TICKER_CACHE_TTL_SECONDS = 86400  # 24h

# {ticker(upper): {"cik": int, "name": str}} — SEC company_tickers.json 메타데이터.
# 회사명(name)은 company_profile 의 US 분기에서 LLM 입력으로 재사용된다.
_ticker_cache: dict[str, dict] = {}
_ticker_cache_expires_at: float = 0.0
_ticker_cache_lock = asyncio.Lock()


class SecEdgarApiClient(ForeignDisclosureApiPort):
    """SEC EDGAR 기반 US 종목 공시 어댑터 (Phase 1: 목록만)"""

    def __init__(self, user_agent: str) -> None:
        # SEC EDGAR requires a User-Agent identifying the requester
        # 참고: example.com / 빈 문자열은 SEC 차단 대상. .env에 실제 이메일 포함 권장.
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        }
        self._submissions_headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }

    async def fetch_recent_filings(
        self,
        ticker: str,
        form_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[ForeignFiling]:
        target_forms = set(form_types or _DEFAULT_FORM_TYPES)

        cik = await self._resolve_cik(ticker)
        if cik is None:
            logger.warning("[SEC EDGAR] CIK not found for ticker=%s", ticker)
            return []

        submissions = await self._fetch_submissions(cik)
        if submissions is None:
            return []

        filings_data = submissions.get("filings", {}).get("recent", {})
        forms = filings_data.get("form", [])
        filed_dates = filings_data.get("filingDate", [])
        report_dates = filings_data.get("reportDate", [])
        descriptions = filings_data.get("primaryDocDescription", [])
        accessions = filings_data.get("accessionNumber", [])

        results: list[ForeignFiling] = []
        for i, form in enumerate(forms):
            if form not in target_forms:
                continue
            filed = filed_dates[i] if i < len(filed_dates) else ""
            report = report_dates[i] if i < len(report_dates) else ""
            desc = descriptions[i] if i < len(descriptions) else form
            acc = accessions[i] if i < len(accessions) else ""
            url = (
                f"https://www.sec.gov/Archives/edgar/full-index/{filed[:4]}/{filed[5:7]}/{acc.replace('-', '')}"
                if acc and filed
                else None
            )
            results.append(ForeignFiling(
                ticker=ticker,
                form_type=form,
                filed_date=filed,
                report_date=report,
                description=desc or form,
                url=url,
                accession_number=acc,
            ))
            if len(results) >= limit:
                break

        return results

    async def resolve_company_name(self, ticker: str) -> Optional[str]:
        """SEC `company_tickers.json` 으로부터 정식 회사명을 조회한다.

        예: "AAPL" → "Apple Inc.". 캐시에 없으면 None.
        """
        cache = await self._get_or_fetch_ticker_cache()
        if cache is None:
            return None
        entry = cache.get(ticker.upper())
        if entry is None:
            logger.warning("[SEC EDGAR] ticker '%s' not in company_tickers.json", ticker)
            return None
        name = entry.get("name")
        return name if isinstance(name, str) and name else None

    async def _resolve_cik(self, ticker: str) -> Optional[int]:
        cache = await self._get_or_fetch_ticker_cache()
        if cache is None:
            return None
        entry = cache.get(ticker.upper())
        if entry is None:
            logger.warning("[SEC EDGAR] ticker '%s' not in company_tickers.json", ticker)
            return None
        cik = entry.get("cik")
        return cik if isinstance(cik, int) else None

    async def _get_or_fetch_ticker_cache(self) -> Optional[dict[str, dict]]:
        global _ticker_cache, _ticker_cache_expires_at
        now = time.monotonic()
        if _ticker_cache and now < _ticker_cache_expires_at:
            return _ticker_cache

        async with _ticker_cache_lock:
            # double-check inside lock
            now = time.monotonic()
            if _ticker_cache and now < _ticker_cache_expires_at:
                return _ticker_cache
            try:
                async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
                    resp = await client.get(_TICKERS_URL)
                    resp.raise_for_status()
                    data = resp.json()
                new_cache: dict[str, dict] = {}
                for entry in data.values():
                    sym = entry.get("ticker", "").upper()
                    if not sym:
                        continue
                    new_cache[sym] = {
                        "cik": int(entry["cik_str"]),
                        "name": entry.get("title", "") or "",
                    }
                _ticker_cache = new_cache
                _ticker_cache_expires_at = time.monotonic() + _TICKER_CACHE_TTL_SECONDS
                logger.info("[SEC EDGAR] ticker cache primed (%d entries)", len(new_cache))
                return _ticker_cache
            except Exception as e:
                logger.warning(
                    "[SEC EDGAR] ticker list fetch failed: %s (%s) — "
                    "SEC may be blocking this User-Agent. Set a real email in SEC_EDGAR_USER_AGENT.",
                    e, type(e).__name__,
                )
                return None

    async def _fetch_submissions(self, cik: int) -> Optional[dict]:
        url = _SUBMISSIONS_URL.format(cik=cik)
        try:
            async with httpx.AsyncClient(headers=self._submissions_headers, timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("[SEC EDGAR] submissions fetch failed for CIK=%d: %s (%s)", cik, e, type(e).__name__)
        return None
