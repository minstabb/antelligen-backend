import logging

from app.common.exception.app_exception import AppException
from app.infrastructure.langgraph.llm_factory import get_workflow_llm
from app.infrastructure.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 분석 전문가(Analyst)입니다.
수집된 정보를 바탕으로 심층 분석을 수행하세요.

분석 결과에 반드시 다음을 포함하세요:
- 핵심 인사이트
- 근거 및 논리적 추론
- 한계점 또는 불확실성
- 정보가 불충분하면 "[NEEDS_MORE_RESEARCH]" 태그를 분석 끝에 추가하세요.
"""


async def analyst_node(state: AgentState) -> dict:
    logger.info("[analyst_node] 시작. research_len=%d", len(state.get("research", "")))

    llm = get_workflow_llm()
    prompt = (
        f"사용자 질문: {state['user_input']}\n\n"
        f"분석 계획:\n{state['plan']}\n\n"
        f"수집된 정보:\n{state['research']}"
    )

    try:
        response = await llm.ainvoke([
            ("system", _SYSTEM_PROMPT),
            ("human", prompt),
        ])
        analysis = response.content
    except Exception as exc:
        logger.error("[analyst_node] LLM 호출 실패: %s", exc)
        raise AppException(status_code=502, message=f"Analyst 노드 오류: {exc}") from exc

    needs_more = "[NEEDS_MORE_RESEARCH]" in analysis
    logger.info("[analyst_node] 완료. needs_more_research=%s", needs_more)
    return {
        "analysis": analysis,
        "messages": [{"role": "analyst", "content": analysis}],
    }
