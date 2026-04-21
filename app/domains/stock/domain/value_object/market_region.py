from enum import Enum


class MarketRegion(Enum):
    KR_KOSPI = "KR_KOSPI"
    KR_KOSDAQ = "KR_KOSDAQ"
    KR_KONEX = "KR_KONEX"
    US_NYSE = "US_NYSE"
    US_NASDAQ = "US_NASDAQ"
    UNKNOWN = "UNKNOWN"

    def is_korea(self) -> bool:
        return self in (MarketRegion.KR_KOSPI, MarketRegion.KR_KOSDAQ, MarketRegion.KR_KONEX)

    def is_us(self) -> bool:
        return self in (MarketRegion.US_NYSE, MarketRegion.US_NASDAQ)
