from app.domains.stock.market_data.domain.service.benchmark_resolver import (
    BenchmarkResolver,
)


def test_us_equity_resolves_to_gspc():
    result = BenchmarkResolver.resolve("AAPL", "EQUITY")
    assert result is not None
    assert result.ticker == "^GSPC"
    assert result.region == "US"


def test_kr_equity_resolves_to_ks11():
    # 6자리 숫자 ticker → MarketRegionResolver 가 KR_KOSPI 추론
    result = BenchmarkResolver.resolve("005930", "EQUITY")
    assert result is not None
    assert result.ticker == "^KS11"
    assert result.region == "KR"


def test_explicit_region_overrides_inference():
    # 알파벳이지만 region="KR" 명시 시 ^KS11
    result = BenchmarkResolver.resolve("UNKNOWNTKR", "EQUITY", region="KR")
    assert result is not None
    assert result.ticker == "^KS11"


def test_etf_returns_none():
    assert BenchmarkResolver.resolve("SPY", "ETF") is None


def test_index_returns_none():
    assert BenchmarkResolver.resolve("^IXIC", "INDEX") is None


def test_mutualfund_returns_none():
    assert BenchmarkResolver.resolve("VFIAX", "MUTUALFUND") is None


def test_unknown_asset_type_returns_none():
    assert BenchmarkResolver.resolve("AAPL", "UNKNOWN") is None
    assert BenchmarkResolver.resolve("AAPL", "") is None


def test_unrecognizable_ticker_returns_none():
    # 7자리 숫자도 알파벳도 아닌 ticker → MarketRegion.UNKNOWN → None
    assert BenchmarkResolver.resolve("$$$", "EQUITY") is None


def test_case_insensitive_asset_type():
    # 소문자 입력도 처리
    result = BenchmarkResolver.resolve("AAPL", "equity")
    assert result is not None
    assert result.ticker == "^GSPC"
