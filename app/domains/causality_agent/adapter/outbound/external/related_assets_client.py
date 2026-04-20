import asyncio
import logging
from datetime import date
from typing import Any, Dict, List

import yfinance as yf

logger = logging.getLogger(__name__)

_ASSETS = [
    ("^VIX", "VIX (변동성 지수)"),
    ("CL=F", "WTI 원유"),
    ("GC=F", "금"),
    ("^TNX", "미국 10년 국채 금리"),
    ("JPY=X", "달러/엔 환율"),
]


class RelatedAssetsClient:
    """VIX·원유·금·미국채·엔화 시계열 수집 (yfinance)."""

    async def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            *[
                loop.run_in_executor(None, self._fetch_one, symbol, name, start_date, end_date)
                for symbol, name in _ASSETS
            ],
            return_exceptions=True,
        )

        assets = []
        for (symbol, name), result in zip(_ASSETS, results):
            if isinstance(result, Exception):
                logger.warning("[RelatedAssets] %s 조회 실패: %s", symbol, result)
                continue
            assets.append(result)
        return assets

    def _fetch_one(
        self,
        symbol: str,
        name: str,
        start_date: date,
        end_date: date,
    ) -> Dict[str, Any]:
        t = yf.Ticker(symbol)
        df = t.history(start=start_date.isoformat(), end=end_date.isoformat(), auto_adjust=True)
        bars = []
        for idx, row in df.iterrows():
            bars.append(
                {
                    "date": idx.date().isoformat(),
                    "close": round(float(row["Close"]), 4),
                }
            )
        return {"symbol": symbol, "name": name, "bars": bars}
