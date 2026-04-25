from app.infrastructure.external.yahoo_ticker import normalize_yfinance_ticker


def test_passthrough_us_equity():
    assert normalize_yfinance_ticker("AAPL") == "AAPL"


def test_already_prefixed_index_unchanged():
    assert normalize_yfinance_ticker("^IXIC") == "^IXIC"


def test_bare_index_symbol_prefixed():
    assert normalize_yfinance_ticker("IXIC") == "^IXIC"
    assert normalize_yfinance_ticker("GSPC") == "^GSPC"
    assert normalize_yfinance_ticker("KS11") == "^KS11"


def test_kr_6digit_appends_ks_suffix():
    assert normalize_yfinance_ticker("005930") == "005930.KS"
    assert normalize_yfinance_ticker("035720") == "035720.KS"


def test_kr_ticker_with_suffix_unchanged():
    assert normalize_yfinance_ticker("005930.KS") == "005930.KS"
    assert normalize_yfinance_ticker("068270.KQ") == "068270.KQ"


def test_non_6digit_numeric_unchanged():
    assert normalize_yfinance_ticker("12345") == "12345"
    assert normalize_yfinance_ticker("1234567") == "1234567"
