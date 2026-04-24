"""
LangChain Tool Use용 도구 정의 + 실행기.

모든 도구는 이미 state에 수집된 데이터를 조회한다 — 추가 외부 호출 없음.
"""
import json
import statistics
from typing import Any, Dict, List

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


_EXECUTORS = {
    "get_price_stats": _exec_get_price_stats,
    "get_correlated_asset": _exec_get_correlated_asset,
    "fetch_news_headlines": _exec_fetch_news_headlines,
    "get_fred_series": _exec_get_fred_series,
    "get_gpr_summary": _exec_get_gpr_summary,
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

    return [
        StructuredTool.from_function(get_price_stats),
        StructuredTool.from_function(get_correlated_asset),
        StructuredTool.from_function(fetch_news_headlines),
        StructuredTool.from_function(get_fred_series),
        StructuredTool.from_function(get_gpr_summary),
    ]
