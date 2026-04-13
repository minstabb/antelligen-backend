import logging

from langgraph.graph import END, START, StateGraph

from app.infrastructure.langgraph.nodes.analyst_node import analyst_node
from app.infrastructure.langgraph.nodes.planner_node import planner_node
from app.infrastructure.langgraph.nodes.researcher_node import researcher_node
from app.infrastructure.langgraph.nodes.reviewer_node import reviewer_node
from app.infrastructure.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 2


def _route_after_analyst(state: AgentState) -> str:
    """analyst 이후 조건부 라우팅.

    분석 결과에 [NEEDS_MORE_RESEARCH] 태그가 있고 반복 횟수가 남아 있으면
    researcher로, 그렇지 않으면 reviewer로 이동한다.
    """
    needs_more = "[NEEDS_MORE_RESEARCH]" in state.get("analysis", "")
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", _MAX_ITERATIONS)

    if needs_more and iteration < max_iter:
        logger.info("[routing] researcher 재실행. iteration=%d/%d", iteration, max_iter)
        return "researcher"

    logger.info("[routing] reviewer 진행. iteration=%d/%d", iteration, max_iter)
    return "reviewer"


def build_workflow_graph():
    """그래프를 빌드하고 컴파일된 인스턴스를 반환한다.

    흐름:
        START → planner → researcher → analyst
                                          ↓ (조건부)
                          researcher ←──[NEEDS_MORE_RESEARCH]
                                          ↓ (충분)
                                       reviewer → END
    """
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("reviewer", reviewer_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_conditional_edges(
        "analyst",
        _route_after_analyst,
        {"researcher": "researcher", "reviewer": "reviewer"},
    )
    graph.add_edge("reviewer", END)

    compiled = graph.compile()
    logger.info("[graph_builder] 멀티 에이전트 그래프 컴파일 완료")
    return compiled


_compiled_graph = None


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_workflow_graph()
    return _compiled_graph
