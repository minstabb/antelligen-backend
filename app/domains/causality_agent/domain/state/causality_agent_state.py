from datetime import date
from typing import Any, Dict, List, Optional, TypedDict


class Hypothesis(TypedDict):
    hypothesis: str
    supporting_tools_called: List[str]


class OHLCVBar(TypedDict):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class FredSeries(TypedDict):
    series_id: str       # FEDFUNDS | CPIAUCSL | UNRATE
    observations: List[Dict[str, Any]]  # [{date, value}]


class RelatedAssetBar(TypedDict):
    symbol: str
    name: str
    bars: List[Dict[str, Any]]  # [{date, close}]


class NewsArticle(TypedDict, total=False):
    date: str
    title: str
    url: str
    tone: float
    source: str  # "finnhub" | "gdelt" | "yfinance"


class GprObservation(TypedDict):
    date: str
    gpr: float


class CausalityAgentState(TypedDict):
    # ── 입력 ──────────────────────────────────────────────────
    ticker: str
    start_date: date
    end_date: date

    # ── gather_situation 노드 출력 ─────────────────────────────
    ohlcv_bars: List[OHLCVBar]
    fred_series: List[FredSeries]          # 금리·CPI·실업률

    # ── collect_non_economic 노드 출력 ────────────────────────
    related_assets: List[RelatedAssetBar]  # VIX·원유·금·미국채·엔화
    news_articles: List[NewsArticle]       # Finnhub + GDELT + yfinance fallback
    gpr_observations: List[GprObservation]

    # ── generate_hypotheses 노드 출력 ────────────────────────
    hypotheses: List[Hypothesis]
    tool_call_log: List[str]               # Claude가 실제 호출한 도구 이름 목록

    # ── 공통 메타 ─────────────────────────────────────────────
    errors: List[str]                      # 개별 수집 실패 메시지 누적
