from datetime import datetime


class CollectedStockData:
    def __init__(
        self,
        ticker: str,
        stock_name: str,
        market: str,
        source: str,
        collected_at: datetime,
        collected_types: list[str],
        dedup_key: str,
        dedup_basis: str,
        company_summary: str | None,
        current_price: str | None,
        currency: str | None,
        market_cap: str | None,
        pe_ratio: str | None,
        dividend_yield: str | None,
        document_text: str | None,
        reference_url: str | None = None,
    ):
        self.ticker = ticker
        self.stock_name = stock_name
        self.market = market
        self.source = source
        self.collected_at = collected_at
        self.collected_types = collected_types
        self.dedup_key = dedup_key
        self.dedup_basis = dedup_basis
        self.company_summary = company_summary
        self.current_price = current_price
        self.currency = currency
        self.market_cap = market_cap
        self.pe_ratio = pe_ratio
        self.dividend_yield = dividend_yield
        self.document_text = document_text
        self.reference_url = reference_url
