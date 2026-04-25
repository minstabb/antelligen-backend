"""yfinance가 요구하는 티커 표기 정규화.

사용자/프론트가 `IXIC`, `GSPC`, `KS11` 같은 bare 심볼을 보낼 때 yfinance는
`^` prefix가 없으면 404로 응답한다. 입력 경계에서 이 매핑을 적용해
downstream 전 구간이 canonical 표기(`^IXIC` 등)를 받도록 한다.

한국 6자리 숫자 티커는 기본 `.KS`(KOSPI)로 매핑하되,
`YahooFinanceStockClient`가 `.KS` fetch 실패(빈 데이터) 시 `.KQ`(KOSDAQ)로
재시도한다(§13.4 A2 lazy fallback).
"""

from typing import Dict, List

INDEX_TICKER_MAP: Dict[str, str] = {
    "IXIC": "^IXIC",
    "DJI": "^DJI",
    "INDU": "^DJI",
    "GSPC": "^GSPC",
    "SPX": "^GSPC",
    "RUT": "^RUT",
    "VIX": "^VIX",
    "FTSE": "^FTSE",
    "N225": "^N225",
    "HSI": "^HSI",
    "GDAXI": "^GDAXI",
    "KS11": "^KS11",
    "KQ11": "^KQ11",
    "KS200": "^KS200",
    "SSEC": "000001.SS",
    "TNX": "^TNX",
}


def normalize_yfinance_ticker(ticker: str) -> str:
    """기본 yfinance 심볼로 변환 (KR 6자리는 `.KS` 우선)."""
    if ticker.startswith("^"):
        return ticker
    if ticker.isdigit() and len(ticker) == 6:
        return f"{ticker}.KS"
    return INDEX_TICKER_MAP.get(ticker, ticker)


def resolve_yfinance_ticker(ticker: str) -> str:
    """alias — `normalize_yfinance_ticker`와 동일하나 이름만 명확."""
    return normalize_yfinance_ticker(ticker)


def candidate_yfinance_tickers(ticker: str) -> List[str]:
    """시도 순서대로 yfinance 심볼 후보를 반환.

    KR 6자리 숫자 티커: `.KS` → `.KQ` (KOSDAQ 폴백) 순서.
    나머지는 단일 결과.
    """
    if ticker.startswith("^"):
        return [ticker]
    if ticker.isdigit() and len(ticker) == 6:
        return [f"{ticker}.KS", f"{ticker}.KQ"]
    mapped = INDEX_TICKER_MAP.get(ticker, ticker)
    return [mapped]
