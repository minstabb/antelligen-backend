import logging

from app.common.exception.app_exception import AppException
from app.infrastructure.langgraph.llm_factory import get_workflow_llm
from app.infrastructure.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 분석 계획 전문가(Planner)입니다.
사용자의 질문을 받아 체계적인 분석 계획을 수립하세요.

다음 형식으로 계획을 작성하세요:
1. 핵심 질문 정의
2. 필요한 정보 목록
3. 분석 접근 방법
4. 예상 결론 범위
"""


async def planner_node(state: AgentState) -> dict:
    logger.info("[planner_node] 시작. input=%s", state["user_input"][:80])

    llm = get_workflow_llm()
    try:
        response = await llm.ainvoke([
            ("system", _SYSTEM_PROMPT),
            ("human", state["user_input"]),
        ])
        plan = response.content
    except Exception as exc:
        logger.error("[planner_node] LLM 호출 실패: %s", exc)
        raise AppException(status_code=502, message=f"Planner 노드 오류: {exc}") from exc

    logger.info("[planner_node] 완료. plan_len=%d", len(plan))
    return {
        "plan": plan,
        "messages": [{"role": "planner", "content": plan}],
        "status": "running",
    }
