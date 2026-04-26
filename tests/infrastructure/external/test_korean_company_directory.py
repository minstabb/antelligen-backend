from app.infrastructure.external.korean_company_directory import lookup_korean_name


def test_lookup_by_6digit_code():
    assert lookup_korean_name("005930") == "삼성전자"
    assert lookup_korean_name("000660") == "SK하이닉스"


def test_lookup_strips_yahoo_suffix():
    assert lookup_korean_name("005930.KS") == "삼성전자"
    assert lookup_korean_name("068760.KQ") == "셀트리온제약"


def test_lookup_unknown_returns_none():
    assert lookup_korean_name("999999") is None
    assert lookup_korean_name("AAPL") is None
    assert lookup_korean_name("") is None
