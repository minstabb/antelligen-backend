import logging

from app.common.exception.app_exception import AppException
from app.infrastructure.langgraph.llm_factory import get_workflow_llm
from app.infrastructure.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 정보 수집 전문가(Researcher)입니다.
제공된 분석 계획을 바탕으로 관련 정보를 체계적으로 정리하세요.

다음 항목을 반드시 포함하세요:
- 관련 배경 지식 및 맥락
- 핵심 사실과 데이터 포인트
- 고려해야 할 다양한 관점
"""


async def researcher_node(state: AgentState) -> dict:
    iteration = state.get("iteration", 0)
    logger.info("[researcher_node] 시작. iteration=%d", iteration)

    llm = get_workflow_llm()
    prompt = (
        f"분석 계획:\n{state['plan']}\n\n"
        f"사용자 질문: {state['user_input']}"
    )
    if state.get("analysis"):
        prompt += f"\n\n이전 분석에서 추가 조사가 필요한 부분:\n{state['analysis']}"

    try:
        response = await llm.ainvoke([
            ("system", _SYSTEM_PROMPT),
            ("human", prompt),
        ])
        research = response.content
    except Exception as exc:
        logger.error("[researcher_node] LLM 호출 실패: %s", exc)
        raise AppException(status_code=502, message=f"Researcher 노드 오류: {exc}") from exc

    logger.info("[researcher_node] 완료. research_len=%d", len(research))
    return {
        "research": research,
        "messages": [{"role": "researcher", "content": research}],
        "iteration": iteration + 1,
    }
