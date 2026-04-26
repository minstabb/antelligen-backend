from app.domains.stock.domain.service.market_region_resolver import MarketRegionResolver
from app.domains.stock.domain.value_object.market_region import MarketRegion


def test_market_hint_takes_priority():
    assert MarketRegionResolver.resolve("AAPL", "KOSPI") == MarketRegion.KR_KOSPI
    assert MarketRegionResolver.resolve("005930", "NASDAQ") == MarketRegion.US_NASDAQ


def test_6digit_numeric_defaults_to_kospi():
    assert MarketRegionResolver.resolve("005930") == MarketRegion.KR_KOSPI
    assert MarketRegionResolver.resolve("068760") == MarketRegion.KR_KOSPI


def test_yahoo_ks_suffix_resolves_kospi():
    assert MarketRegionResolver.resolve("005930.KS") == MarketRegion.KR_KOSPI
    assert MarketRegionResolver.resolve("000660.KS") == MarketRegion.KR_KOSPI


def test_yahoo_kq_suffix_resolves_kosdaq():
    assert MarketRegionResolver.resolve("068760.KQ") == MarketRegion.KR_KOSDAQ
    assert MarketRegionResolver.resolve("247540.KQ") == MarketRegion.KR_KOSDAQ


def test_alpha_ticker_defaults_to_us_nasdaq():
    assert MarketRegionResolver.resolve("AAPL") == MarketRegion.US_NASDAQ
    assert MarketRegionResolver.resolve("NVDA") == MarketRegion.US_NASDAQ


def test_unknown_ticker_returns_unknown():
    assert MarketRegionResolver.resolve("^IXIC") == MarketRegion.UNKNOWN
    assert MarketRegionResolver.resolve("12345") == MarketRegion.UNKNOWN
    assert MarketRegionResolver.resolve("005930.XX") == MarketRegion.UNKNOWN


def test_is_korea_helper_covers_all_kr_regions():
    assert MarketRegionResolver.resolve("005930").is_korea() is True
    assert MarketRegionResolver.resolve("068760.KQ").is_korea() is True
    assert MarketRegionResolver.resolve("AAPL").is_korea() is False
