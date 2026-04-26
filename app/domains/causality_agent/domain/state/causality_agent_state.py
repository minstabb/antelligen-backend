from datetime import date
from typing import Any, Dict, List, TypedDict


class HypothesisSource(TypedDict, total=False):
    label: str
    url: str


class Hypothesis(TypedDict, total=False):
    hypothesis: str
    supporting_tools_called: List[str]
    confidence: str          # HIGH | MEDIUM | LOW
    layer: str               # DIRECT | SUPPORTING | MARKET
    sources: List[HypothesisSource]
    evidence: str


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


class AnnouncementItem(TypedDict, total=False):
    date: str         # "YYYY-MM-DD"
    type: str         # AnnouncementEventType.value (MERGER_ACQUISITION, EARNINGS_RELEASE, ...)
    title: str        # 공시명/8-K Item 본문 요약
    source: str       # "sec_edgar" | "dart"
    url: str
    items_str: str    # SEC 8-K Item 코드(예: "1.01,9.01"). DART 는 부재


class AnalystRecommendation(TypedDict, total=False):
    period: str       # "YYYY-MM-DD" (월 1일 기준)
    buy: int
    hold: int
    sell: int
    strong_buy: int
    strong_sell: int


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
    news_articles: List[NewsArticle]       # Finnhub + GDELT + yfinance fallback + Naver(KR)
    gpr_observations: List[GprObservation]
    announcements: List[AnnouncementItem]  # SEC EDGAR 8-K 공시 (미국). DART 는 별도 후속 PR.
    analyst_recommendations: List[AnalystRecommendation]  # Finnhub buy/hold/sell 월별 트렌드 (미국)

    # ── generate_hypotheses 노드 출력 ────────────────────────
    hypotheses: List[Hypothesis]
    tool_call_log: List[str]               # Claude가 실제 호출한 도구 이름 목록

    # ── 공통 메타 ─────────────────────────────────────────────
    errors: List[str]                      # 개별 수집 실패 메시지 누적
