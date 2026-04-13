import logging

from app.common.exception.app_exception import AppException
from app.infrastructure.langgraph.llm_factory import get_workflow_llm
from app.infrastructure.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 최종 검토 전문가(Reviewer)입니다.
분석 결과를 검토하고 명확하고 실용적인 최종 답변을 작성하세요.

최종 답변에 반드시 포함할 내용:
- 핵심 결론 (간결하고 명확하게)
- 주요 근거 요약
- 실용적 시사점 또는 권고사항
"""


async def reviewer_node(state: AgentState) -> dict:
    logger.info("[reviewer_node] 시작. analysis_len=%d", len(state.get("analysis", "")))

    llm = get_workflow_llm()
    prompt = (
        f"사용자 질문: {state['user_input']}\n\n"
        f"분석 결과:\n{state['analysis']}"
    )

    try:
        response = await llm.ainvoke([
            ("system", _SYSTEM_PROMPT),
            ("human", prompt),
        ])
        final_output = response.content
    except Exception as exc:
        logger.error("[reviewer_node] LLM 호출 실패: %s", exc)
        raise AppException(status_code=502, message=f"Reviewer 노드 오류: {exc}") from exc

    logger.info("[reviewer_node] 완료. output_len=%d", len(final_output))
    return {
        "final_output": final_output,
        "messages": [{"role": "reviewer", "content": final_output}],
        "status": "completed",
    }
