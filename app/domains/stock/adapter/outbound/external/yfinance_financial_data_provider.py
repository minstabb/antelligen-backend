import asyncio
import logging
from datetime import datetime, date
from typing import Optional

from app.domains.stock.application.port.foreign_financial_data_provider import ForeignFinancialDataProvider
from app.domains.stock.domain.entity.financial_ratio import FinancialRatio
from app.domains.stock.domain.value_object.earnings_release import EarningsRelease

logger = logging.getLogger(__name__)


def _fetch_sync(ticker: str) -> dict:
    """blocking yfinance 호출 — asyncio.to_thread 에서 실행."""
    import yfinance as yf  # 런타임 import (선택적 의존성)

    t = yf.Ticker(ticker)
    info = t.info or {}

    ratios: dict = {
        "info": info,
        "earnings": None,
    }

    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            ratios["earnings"] = ed.reset_index().iloc[0].to_dict()
    except Exception:
        pass

    return ratios


class YfinanceFinancialDataProvider(ForeignFinancialDataProvider):
    """yfinance 기반 US 종목 재무 데이터 어댑터"""

    async def fetch_financial_ratios(self, ticker: str) -> Optional[FinancialRatio]:
        try:
            data = await asyncio.to_thread(_fetch_sync, ticker)
        except Exception as e:
            logger.warning("[yfinance] fetch_financial_ratios failed for %s: %s", ticker, e)
            return None

        info = data.get("info", {})
        if not info:
            return None

        return FinancialRatio(
            ticker=ticker,
            corp_code="",  # US는 corp_code 없음
            fiscal_year=str(datetime.now().year),
            roe=_safe_float(info.get("returnOnEquity")) and _safe_float(info.get("returnOnEquity")) * 100,
            roa=_safe_float(info.get("returnOnAssets")) and _safe_float(info.get("returnOnAssets")) * 100,
            per=_safe_float(info.get("trailingPE")),
            pbr=_safe_float(info.get("priceToBook")),
            debt_ratio=_safe_float(info.get("debtToEquity")),
            sales=_safe_float(info.get("totalRevenue")),
            operating_income=_safe_float(info.get("operatingIncome") or info.get("ebitda")),
            net_income=_safe_float(info.get("netIncomeToCommon")),
            collected_at=datetime.now(),
        )

    async def fetch_recent_earnings(self, ticker: str) -> Optional[EarningsRelease]:
        try:
            data = await asyncio.to_thread(_fetch_sync, ticker)
        except Exception as e:
            logger.warning("[yfinance] fetch_recent_earnings failed for %s: %s", ticker, e)
            return None

        row = data.get("earnings")
        if not row:
            return None

        report_date = None
        try:
            raw_date = row.get("Earnings Date")
            if raw_date is not None:
                report_date = date.fromisoformat(str(raw_date)[:10])
        except Exception:
            pass

        eps = _safe_float(row.get("EPS Estimate") or row.get("Reported EPS"))

        return EarningsRelease(
            ticker=ticker,
            report_date=report_date,
            eps=eps,
            is_preliminary=False,  # US quarterly release is final
            source="yfinance",
        )


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None
