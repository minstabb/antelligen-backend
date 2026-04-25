"""SEC EDGAR non-US ticker 조기 반환 필터 — S2-6 회귀 방지."""
import pytest

from app.domains.dashboard.adapter.outbound.external.sec_edgar_announcement_client import (
    _is_non_us_ticker,
)


@pytest.mark.parametrize(
    "ticker",
    [
        "^IXIC",  # NASDAQ Composite
        "^GSPC",  # S&P 500
        "^VIX",   # Volatility Index
        "^TNX",   # 10Y Treasury
        "^KS11",  # KOSPI
        "005930.KS",   # 삼성전자
        "068270.KQ",   # 셀트리온헬스케어
        "7203.T",      # Toyota (Tokyo)
        "0700.HK",     # Tencent
        "600519.SS",   # Kweichow Moutai (Shanghai)
        "000333.SZ",   # Midea (Shenzhen)
        "HSBA.L",      # HSBC (London)
        "MC.PA",       # LVMH (Paris)
        "SAP.DE",      # SAP (Xetra)
        "SHOP.TO",     # Shopify (Toronto)
        "CBA.AX",      # Commonwealth Bank (Sydney)
    ],
)
def test_non_us_ticker_detected(ticker):
    assert _is_non_us_ticker(ticker) is True


@pytest.mark.parametrize(
    "ticker",
    [
        "AAPL",
        "NVDA",
        "MSFT",
        "SPY",   # US ETF
        "QQQ",
        "BRK.B",  # .B는 클래스 구분, non-US suffix 아님
        "BRK.A",
    ],
)
def test_us_ticker_passes(ticker):
    assert _is_non_us_ticker(ticker) is False


def test_case_insensitive():
    assert _is_non_us_ticker("005930.ks") is True
    assert _is_non_us_ticker("^ixic") is True
    assert _is_non_us_ticker("aapl") is False
