import logging
from datetime import date

from langgraph.graph import StateGraph

from app.domains.causality_agent.application.node.collect_non_economic_node import (
    collect_non_economic,
)
from app.domains.causality_agent.application.node.gather_situation_node import gather_situation
from app.domains.causality_agent.application.node.generate_hypotheses_node import (
    generate_hypotheses,
)
from app.domains.causality_agent.domain.state.causality_agent_state import CausalityAgentState

logger = logging.getLogger(__name__)

_NODE_SITUATION = "gather_situation"
_NODE_NON_ECONOMIC = "collect_non_economic"
_NODE_HYPOTHESES = "generate_hypotheses"


def _build_graph() -> StateGraph:
    g = StateGraph(CausalityAgentState)
    g.add_node(_NODE_SITUATION, gather_situation)
    g.add_node(_NODE_NON_ECONOMIC, collect_non_economic)
    g.add_node(_NODE_HYPOTHESES, generate_hypotheses)

    # gather_situation → collect_non_economic → generate_hypotheses
    g.add_edge(_NODE_SITUATION, _NODE_NON_ECONOMIC)
    g.add_edge(_NODE_NON_ECONOMIC, _NODE_HYPOTHESES)

    g.set_entry_point(_NODE_SITUATION)
    g.set_finish_point(_NODE_HYPOTHESES)
    return g


_compiled = _build_graph().compile()


async def run_causality_agent(
    ticker: str,
    start_date: date,
    end_date: date,
) -> CausalityAgentState:
    """CausalityAgent 워크플로우 실행 진입점."""
    initial: CausalityAgentState = {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "ohlcv_bars": [],
        "fred_series": [],
        "related_assets": [],
        "news_articles": [],
        "gpr_observations": [],
        "hypotheses": [],
        "tool_call_log": [],
        "errors": [],
    }
    logger.info("[CausalityAgent] ══════════════════════════════════════")
    logger.info("[CausalityAgent] 시작: ticker=%s, 기간=%s ~ %s", ticker, start_date, end_date)
    logger.info("[CausalityAgent] ══════════════════════════════════════")
    result = await _compiled.ainvoke(initial)
    logger.info(
        "[CausalityAgent] 완료: ticker=%s, ohlcv=%d, fred=%d, assets=%d, "
        "news=%d, gpr=%d, hypotheses=%d, tools=%s, errors=%d",
        ticker,
        len(result.get("ohlcv_bars", [])),
        len(result.get("fred_series", [])),
        len(result.get("related_assets", [])),
        len(result.get("news_articles", [])),
        len(result.get("gpr_observations", [])),
        len(result.get("hypotheses", [])),
        result.get("tool_call_log", []),
        len(result.get("errors", [])),
    )
    return result
