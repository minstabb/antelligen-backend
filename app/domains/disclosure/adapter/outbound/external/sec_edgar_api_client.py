import logging
from typing import Optional

import httpx

from app.domains.disclosure.application.port.foreign_disclosure_api_port import ForeignDisclosureApiPort
from app.domains.disclosure.domain.entity.foreign_filing import ForeignFiling

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FILING_VIEWER_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"

_DEFAULT_FORM_TYPES = ["8-K", "10-K", "10-Q"]


class SecEdgarApiClient(ForeignDisclosureApiPort):
    """SEC EDGAR 기반 US 종목 공시 어댑터 (Phase 1: 목록만)"""

    def __init__(self, user_agent: str) -> None:
        # SEC EDGAR requires a User-Agent identifying the requester
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}

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

    async def _resolve_cik(self, ticker: str) -> Optional[int]:
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=10) as client:
                resp = await client.get(_TICKERS_URL)
                resp.raise_for_status()
                data = resp.json()
            upper = ticker.upper()
            for entry in data.values():
                if entry.get("ticker", "").upper() == upper:
                    return int(entry["cik_str"])
        except Exception as e:
            logger.warning("[SEC EDGAR] CIK lookup failed for %s: %s", ticker, e)
        return None

    async def _fetch_submissions(self, cik: int) -> Optional[dict]:
        url = _SUBMISSIONS_URL.format(cik=cik)
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("[SEC EDGAR] submissions fetch failed for CIK=%d: %s", cik, e)
        return None
