from datetime import datetime, timezone

import httpx

from app.domains.stock.application.port.stock_data_collector import StockDataCollector
from app.domains.stock.domain.entity.raw_collected_stock_data import (
    RawCollectedStockData,
)


class SerpStockDataCollector(StockDataCollector):
    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def collect(
        self, ticker: str, stock_name: str, market: str
    ) -> RawCollectedStockData | None:
        params = {
            "engine": "google_finance",
            "q": self._build_query(ticker=ticker, market=market),
            "hl": "ko",
            "api_key": self._api_key,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            return None

        return RawCollectedStockData(
            ticker=ticker,
            stock_name=stock_name,
            market=market,
            source="serpapi/google_finance",
            collected_at=datetime.now(timezone.utc),
            raw_payload=data,
        )

    def _build_query(self, ticker: str, market: str) -> str:
        if market.upper() in {"KOSPI", "KOSDAQ", "KONEX"}:
            return f"{ticker}:KRX"
        return ticker
