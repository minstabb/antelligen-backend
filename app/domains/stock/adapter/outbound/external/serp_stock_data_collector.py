from datetime import datetime, timezone

from app.domains.stock.application.port.stock_data_collector import StockDataCollector
from app.domains.stock.domain.entity.raw_collected_stock_data import (
    RawCollectedStockData,
)
from app.infrastructure.external.serp_client import SerpClient


class SerpStockDataCollector(StockDataCollector):
    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str):
        self._client = SerpClient(api_key=api_key)

    async def collect(
        self, ticker: str, stock_name: str, market: str
    ) -> RawCollectedStockData | None:
        params = {
            "engine": "google_finance",
            "q": self._build_query(ticker=ticker, market=market),
            "hl": "ko",
        }

        data = await self._client.get(params)

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
