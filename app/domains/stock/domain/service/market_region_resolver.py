from app.domains.stock.domain.value_object.market_region import MarketRegion

_MARKET_HINT_MAP: dict[str, MarketRegion] = {
    "KOSPI": MarketRegion.KR_KOSPI,
    "KOSDAQ": MarketRegion.KR_KOSDAQ,
    "KONEX": MarketRegion.KR_KONEX,
    "NYSE": MarketRegion.US_NYSE,
    "NASDAQ": MarketRegion.US_NASDAQ,
}


class MarketRegionResolver:
    """ticker + market hint → MarketRegion. hint 우선, 없으면 형식 추론."""

    @staticmethod
    def resolve(ticker: str, market_hint: str | None = None) -> MarketRegion:
        if market_hint:
            resolved = _MARKET_HINT_MAP.get(market_hint.upper())
            if resolved:
                return resolved

        if ticker.isdigit() and len(ticker) == 6:
            return MarketRegion.KR_KOSPI  # 6자리 숫자 → KR (KOSPI 기본값)

        if ticker.isalpha() and 1 <= len(ticker) <= 5:
            return MarketRegion.US_NASDAQ  # 알파벳 1-5자 → US (NASDAQ 기본값)

        return MarketRegion.UNKNOWN
