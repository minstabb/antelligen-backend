from datetime import datetime


class RawCollectedStockData:
    def __init__(
        self,
        ticker: str,
        stock_name: str,
        market: str,
        source: str,
        collected_at: datetime,
        raw_payload: dict,
    ):
        self.ticker = ticker
        self.stock_name = stock_name
        self.market = market
        self.source = source
        self.collected_at = collected_at
        self.raw_payload = raw_payload
