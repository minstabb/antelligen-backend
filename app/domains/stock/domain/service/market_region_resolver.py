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

        # Yahoo Finance 표기: `005930.KS` (KOSPI), `005930.KQ` (KOSDAQ)
        if "." in ticker:
            code, _, suffix = ticker.partition(".")
            if code.isdigit() and len(code) == 6:
                if suffix.upper() == "KS":
                    return MarketRegion.KR_KOSPI
                if suffix.upper() == "KQ":
                    return MarketRegion.KR_KOSDAQ

        if ticker.isalpha() and 1 <= len(ticker) <= 5:
            return MarketRegion.US_NASDAQ  # 알파벳 1-5자 → US (NASDAQ 기본값)

        return MarketRegion.UNKNOWN
