import logging
import time

from app.infrastructure.langgraph.graph_builder import get_compiled_graph
from app.infrastructure.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 2


async def run_workflow(
    user_input: str,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> AgentState:
    """멀티 에이전트 워크플로우 단일 진입점.

    Args:
        user_input: 사용자 질문 또는 분석 요청 문자열
        max_iterations: researcher → analyst 최대 반복 횟수 (기본값 2)

    Returns:
        AgentState: final_output, messages, status, iteration 등을 담은 최종 상태

    Raises:
        AppException: 노드 내 LLM 호출 실패 시 502로 전파
    """
    logger.info("[run_workflow] 시작. input=%s", user_input[:80])
    started_at = time.perf_counter()

    initial_state: AgentState = {
        "user_input": user_input,
        "messages": [],
        "plan": "",
        "research": "",
        "analysis": "",
        "final_output": "",
        "iteration": 0,
        "max_iterations": max_iterations,
        "status": "running",
        "error": None,
    }

    graph = get_compiled_graph()
    result: AgentState = await graph.ainvoke(initial_state)

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "[run_workflow] 완료. status=%s elapsed_ms=%d nodes=%s",
        result.get("status"),
        elapsed_ms,
        [m["role"] for m in result.get("messages", [])],
    )

    return result
