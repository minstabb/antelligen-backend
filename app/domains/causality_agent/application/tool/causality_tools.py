"""
LangChain Tool Use용 도구 정의 + 실행기.

모든 도구는 이미 state에 수집된 데이터를 조회한다 — 추가 외부 호출 없음.
"""
import json
import statistics
from typing import Any, Dict, List, Optional

from langchain_core.tools import StructuredTool

from app.domains.causality_agent.domain.state.causality_agent_state import CausalityAgentState

# ─────────────────────────────────────────────────────────────
# Anthropic 형식 스키마 (참고용 — LangChain 팩토리가 실제 사용)
# ─────────────────────────────────────────────────────────────

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "get_price_stats",
        "description": (
            "분석 대상 종목(ticker)의 OHLCV 데이터에서 수익률·변동성·최대낙폭을 계산한다. "
            "window_days로 최근 N 거래일만 사용할 수 있다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": "최근 N 거래일 (0이면 전체 기간)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_correlated_asset",
        "description": (
            "연관 자산(VIX·원유·금·미국채·엔화)의 종가 시계열을 반환한다. "
            "symbol은 ^VIX | CL=F | GC=F | ^TNX | JPY=X 중 하나."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "enum": ["^VIX", "CL=F", "GC=F", "^TNX", "JPY=X"],
                    "description": "연관 자산 심볼",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "fetch_news_headlines",
        "description": (
            "Finnhub + GDELT + yfinance에서 수집된 뉴스 헤드라인을 키워드로 필터링해 반환한다. "
            "keyword를 포함하는 기사만 반환하며 max_results로 개수를 제한한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "필터링할 키워드 (대소문자 무시)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 반환 기사 수 (기본 10)",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_fred_series",
        "description": (
            "FRED 경제지표 시계열(관측값 목록)을 반환한다. "
            "series_id: FEDFUNDS(기준금리) | CPIAUCSL(CPI) | UNRATE(실업률)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "enum": ["FEDFUNDS", "CPIAUCSL", "UNRATE"],
                    "description": "FRED 시리즈 ID",
                }
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "get_gpr_summary",
        "description": "수집된 GPR(지정학적 리스크) 지수의 평균·최대·최근값 및 추세를 반환한다.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_announcements",
        "description": (
            "수집된 공시(미국 SEC 8-K + 한국 DART) 리스트를 키워드로 필터링해 반환한다. "
            "ticker 가 한국 종목이면 DART list.json, 미국 종목이면 SEC EDGAR 가 사전에 수집됨. "
            "type 필드: EARNINGS_RELEASE / EARNINGS_GUIDANCE(잠정실적) / TREASURY_STOCK / "
            "STOCK_SPLIT / RIGHTS_OFFERING / BONUS_ISSUE / MERGER_ACQUISITION / "
            "DEBT_ISSUANCE / CRISIS / MAJOR_EVENT 등. "
            "source 필드: 'sec_edgar' | 'dart'. keyword 빈 문자열이면 전체 반환."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "title 에 포함되어야 할 키워드 (대소문자 무시, 비우면 전체)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "최대 반환 건수 (기본 10)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_analyst_recommendations",
        "description": (
            "수집된 분석가 추천(Finnhub buy/hold/sell 월별 트렌드)을 반환한다. "
            "최근 N개월 + 직전 달 대비 buy/sell 비율 변화 요약. 미국 종목 한정. "
            "한국/지수는 빈 결과."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "description": "최근 N개월만 반환 (기본 6, 0이면 전체)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_market_comparison",
        "description": (
            "분석 대상 종목의 같은 기간 수익률을 시장 벤치마크(한국=^KS11/KOSPI, 미국=^GSPC/S&P500)와 비교한다. "
            "종목 영향과 시장 전체 영향을 분리하기 위한 alpha 계산. window_days=0 이면 전체 수집 기간."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": "최근 N 거래일 (0=전체)",
                }
            },
            "required": [],
        },
    },
]


# ─────────────────────────────────────────────────────────────
# 실행기 — state를 읽어 결과를 반환 (순수 Python, 외부 IO 없음)
# ─────────────────────────────────────────────────────────────

def _exec_get_price_stats(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    bars = state.get("ohlcv_bars", [])
    window = int(inputs.get("window_days", 0))
    if window > 0:
        bars = bars[-window:]
    if len(bars) < 2:
        return json.dumps({"error": "OHLCV 데이터 부족"})

    closes = [b["close"] for b in bars]
    daily_returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    total_return = (closes[-1] - closes[0]) / closes[0]
    volatility = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0

    peak = closes[0]
    max_drawdown = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak
        if dd > max_drawdown:
            max_drawdown = dd

    return json.dumps(
        {
            "period_days": len(bars),
            "start_close": closes[0],
            "end_close": closes[-1],
            "total_return_pct": round(total_return * 100, 2),
            "daily_volatility_pct": round(volatility * 100, 4),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
        }
    )


def _exec_get_correlated_asset(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    symbol = inputs.get("symbol", "")
    assets = state.get("related_assets", [])
    for asset in assets:
        if asset["symbol"] == symbol:
            bars = asset["bars"]
            closes = [b["close"] for b in bars]
            if len(closes) >= 2:
                chg = (closes[-1] - closes[0]) / closes[0] * 100
            else:
                chg = None
            return json.dumps(
                {
                    "symbol": symbol,
                    "name": asset["name"],
                    "count": len(bars),
                    "first_date": bars[0]["date"] if bars else None,
                    "last_date": bars[-1]["date"] if bars else None,
                    "first_close": closes[0] if closes else None,
                    "last_close": closes[-1] if closes else None,
                    "period_change_pct": round(chg, 2) if chg is not None else None,
                    "bars": bars[-30:],  # 최근 30개만 반환해 토큰 절약
                }
            )
    return json.dumps({"error": f"{symbol} 데이터 없음"})


def _exec_fetch_news_headlines(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    keyword = inputs.get("keyword", "").lower()
    max_results = int(inputs.get("max_results", 10))
    articles = state.get("news_articles", [])
    matched = [a for a in articles if keyword in a.get("title", "").lower()]
    return json.dumps(
        {
            "keyword": keyword,
            "total_matched": len(matched),
            "articles": matched[:max_results],
        }
    )


def _exec_get_fred_series(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    series_id = inputs.get("series_id", "")
    for s in state.get("fred_series", []):
        if s["series_id"] == series_id:
            obs = s["observations"]
            values = [float(o["value"]) for o in obs if o.get("value")]
            summary: Dict[str, Any] = {
                "series_id": series_id,
                "count": len(obs),
                "first_date": obs[0]["date"] if obs else None,
                "last_date": obs[-1]["date"] if obs else None,
                "latest_value": values[-1] if values else None,
                "mean": round(statistics.mean(values), 4) if values else None,
                "recent_observations": obs[-12:],  # 최근 12개월
            }
            return json.dumps(summary)
    return json.dumps({"error": f"{series_id} 데이터 없음"})


def _exec_get_gpr_summary(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    obs = state.get("gpr_observations", [])
    if not obs:
        return json.dumps({"error": "GPR 데이터 없음"})
    values = [o["gpr"] for o in obs]
    half = len(values) // 2
    trend = "상승" if (statistics.mean(values[half:]) > statistics.mean(values[:half])) else "하락"
    return json.dumps(
        {
            "count": len(obs),
            "mean": round(statistics.mean(values), 2),
            "max": round(max(values), 2),
            "min": round(min(values), 2),
            "latest": round(values[-1], 2),
            "trend": trend,
            "recent_observations": obs[-6:],
        }
    )


def _exec_get_announcements(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    keyword = str(inputs.get("keyword", "") or "").lower()
    max_results = int(inputs.get("max_results", 10))
    items = state.get("announcements", [])
    if keyword:
        items = [a for a in items if keyword in a.get("title", "").lower()]
    return json.dumps(
        {
            "keyword": keyword,
            "total_matched": len(items),
            "announcements": items[:max_results],
        }
    )


def _exec_get_analyst_recommendations(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    months = int(inputs.get("months", 6))
    recs = list(state.get("analyst_recommendations", []))
    if not recs:
        return json.dumps({"available": False})

    # period 내림차순 정렬(최신 우선) — Finnhub 응답이 보통 이미 최신순이지만 보장
    recs.sort(key=lambda r: str(r.get("period", "")), reverse=True)
    recent = recs if months <= 0 else recs[:months]

    # 직전 달 대비 buy/sell 변화 요약
    delta: Dict[str, Any] = {}
    if len(recent) >= 2:
        cur, prev = recent[0], recent[1]
        delta = {
            "period": cur.get("period"),
            "prev_period": prev.get("period"),
            "buy_change": cur.get("buy", 0) - prev.get("buy", 0),
            "sell_change": cur.get("sell", 0) - prev.get("sell", 0),
            "strong_buy_change": cur.get("strong_buy", 0) - prev.get("strong_buy", 0),
            "strong_sell_change": cur.get("strong_sell", 0) - prev.get("strong_sell", 0),
        }

    return json.dumps(
        {
            "available": True,
            "count": len(recs),
            "recent": recent,
            "delta_vs_prev": delta,
        }
    )


def _cumulative_pct(bars: List[Dict[str, Any]]) -> Optional[float]:
    """첫 close → 마지막 close cumulative return(%). 데이터 부족/기준가 0 이면 None."""
    if len(bars) < 2:
        return None
    start = bars[0].get("close")
    end = bars[-1].get("close")
    if not start or start <= 0:
        return None
    return (end - start) / start * 100.0


def _exec_get_market_comparison(state: CausalityAgentState, inputs: Dict[str, Any]) -> str:
    benchmark = state.get("market_benchmark")
    if not benchmark:
        return json.dumps({"available": False, "reason": "벤치마크 미수집"})

    bars = state.get("ohlcv_bars", [])
    bm_bars = benchmark.get("bars", [])
    if len(bars) < 2 or len(bm_bars) < 2:
        return json.dumps({"available": False, "reason": "데이터 부족"})

    window = int(inputs.get("window_days", 0))
    if window > 0:
        bars = bars[-window:]
        bm_bars = bm_bars[-window:]
        if len(bars) < 2 or len(bm_bars) < 2:
            return json.dumps({"available": False, "reason": "window 데이터 부족"})

    ticker_return = _cumulative_pct(bars)
    bm_return = _cumulative_pct(bm_bars)
    if ticker_return is None or bm_return is None:
        return json.dumps({"available": False, "reason": "기준가 부정"})

    alpha = ticker_return - bm_return

    response: Dict[str, Any] = {
        "available": True,
        "period_days": len(bars),
        "ticker_return_pct": round(ticker_return, 2),
        "market": {
            "symbol": benchmark.get("symbol"),
            "name": benchmark.get("name"),
            "return_pct": round(bm_return, 2),
            "alpha_pct": round(alpha, 2),
        },
        "interpretation": (
            "시장 대비 outperform" if alpha > 0
            else "시장 대비 underperform" if alpha < 0
            else "시장과 동일"
        ),
    }

    # 섹터 벤치마크 동시 비교 (매핑이 있는 미국 종목만 채워짐)
    sector = state.get("sector_benchmark")
    if sector and sector.get("bars"):
        sb_bars = sector["bars"]
        if window > 0:
            sb_bars = sb_bars[-window:]
        sector_return = _cumulative_pct(sb_bars)
        if sector_return is not None:
            sector_alpha = ticker_return - sector_return
            response["sector"] = {
                "symbol": sector.get("symbol"),
                "name": sector.get("name"),
                "return_pct": round(sector_return, 2),
                "alpha_pct": round(sector_alpha, 2),
                "interpretation": (
                    "섹터 대비 outperform" if sector_alpha > 0
                    else "섹터 대비 underperform" if sector_alpha < 0
                    else "섹터와 동일"
                ),
            }

    return json.dumps(response)


_EXECUTORS = {
    "get_price_stats": _exec_get_price_stats,
    "get_correlated_asset": _exec_get_correlated_asset,
    "fetch_news_headlines": _exec_fetch_news_headlines,
    "get_fred_series": _exec_get_fred_series,
    "get_gpr_summary": _exec_get_gpr_summary,
    "get_announcements": _exec_get_announcements,
    "get_analyst_recommendations": _exec_get_analyst_recommendations,
    "get_market_comparison": _exec_get_market_comparison,
}


def execute_tool(name: str, inputs: Dict[str, Any], state: CausalityAgentState) -> str:
    executor = _EXECUTORS.get(name)
    if executor is None:
        return json.dumps({"error": f"알 수 없는 도구: {name}"})
    try:
        return executor(state, inputs)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ─────────────────────────────────────────────────────────────
# LangChain StructuredTool 팩토리
# state를 클로저로 캡처해 각 도구 함수에 주입한다.
# ─────────────────────────────────────────────────────────────

def make_langchain_tools(state: CausalityAgentState) -> List[StructuredTool]:
    def get_price_stats(window_days: int = 0) -> str:
        """분석 대상 종목의 OHLCV에서 수익률·변동성·최대낙폭을 계산한다. window_days=0이면 전체 기간."""
        return execute_tool("get_price_stats", {"window_days": window_days}, state)

    def get_correlated_asset(symbol: str) -> str:
        """연관 자산 종가 시계열을 반환한다. symbol: ^VIX | CL=F | GC=F | ^TNX | JPY=X"""
        return execute_tool("get_correlated_asset", {"symbol": symbol}, state)

    def fetch_news_headlines(keyword: str, max_results: int = 10) -> str:
        """Finnhub/GDELT/yfinance에서 수집된 뉴스 헤드라인을 키워드로 필터링해 반환한다."""
        return execute_tool("fetch_news_headlines", {"keyword": keyword, "max_results": max_results}, state)

    def get_fred_series(series_id: str) -> str:
        """FRED 경제지표 시계열을 반환한다. series_id: FEDFUNDS | CPIAUCSL | UNRATE"""
        return execute_tool("get_fred_series", {"series_id": series_id}, state)

    def get_gpr_summary() -> str:
        """GPR(지정학적 리스크) 지수의 평균·최대·최근값·추세를 반환한다."""
        return execute_tool("get_gpr_summary", {}, state)

    def get_announcements(keyword: str = "", max_results: int = 10) -> str:
        """수집된 공시(SEC 8-K)를 키워드로 필터링해 반환. keyword 비우면 전체. DART 한국 공시는 후속 PR."""
        return execute_tool(
            "get_announcements",
            {"keyword": keyword, "max_results": max_results},
            state,
        )

    def get_analyst_recommendations(months: int = 6) -> str:
        """Finnhub 분석가 buy/hold/sell 월별 트렌드 + 직전 달 대비 변화 요약. 미국 종목 한정."""
        return execute_tool(
            "get_analyst_recommendations",
            {"months": months},
            state,
        )

    def get_market_comparison(window_days: int = 0) -> str:
        """종목 vs 시장 벤치마크(KR=^KS11 / US=^GSPC) cumulative return 차이(alpha). window_days=0=전체."""
        return execute_tool(
            "get_market_comparison",
            {"window_days": window_days},
            state,
        )

    return [
        StructuredTool.from_function(get_price_stats),
        StructuredTool.from_function(get_correlated_asset),
        StructuredTool.from_function(fetch_news_headlines),
        StructuredTool.from_function(get_fred_series),
        StructuredTool.from_function(get_gpr_summary),
        StructuredTool.from_function(get_announcements),
        StructuredTool.from_function(get_analyst_recommendations),
        StructuredTool.from_function(get_market_comparison),
    ]
