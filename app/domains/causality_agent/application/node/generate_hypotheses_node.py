"""
generate_hypotheses 노드.

수집된 컨텍스트(OHLCV·FRED·연관자산·뉴스·GPR)를 토대로
LangChain Tool Use 루프를 통해 투자 가설을 자율 생성한다.
"""
import json
import logging
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.domains.causality_agent.application.tool.causality_tools import make_langchain_tools
from app.domains.causality_agent.domain.state.causality_agent_state import CausalityAgentState
from app.infrastructure.langgraph.llm_factory import get_workflow_llm

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 8
_MODEL = "gpt-5-mini"

_SYSTEM_PROMPT = """\
당신은 정량 투자 분석 전문가입니다.
제공된 도구를 자율적으로 호출해 시장 데이터를 탐색한 후,
데이터에 근거한 인과 관계 가설을 생성하십시오.

## 가설 작성 기준
- 가설은 인과 관계를 명시해야 한다: "[원인] → [결과]" 형태
- 근거 데이터(지표명, 수치, 날짜)를 가설 안에 포함한다
- 3~6개의 가설을 생성한다
- 서로 독립적인 관점(가격, 거시경제, 지정학, 섹터)을 포함한다

## 최종 출력 형식
도구 호출이 완료된 후 반드시 아래 JSON만 출력한다. 다른 설명은 추가하지 않는다.

```json
[
  {
    "hypothesis": "가설 내용 (한국어, 2~4문장)",
    "supporting_tools_called": ["tool_name_1", "tool_name_2"]
  }
]
```
"""


def _build_context_message(state: CausalityAgentState) -> str:
    ticker = state["ticker"]
    start = state["start_date"].isoformat()
    end = state["end_date"].isoformat()

    ohlcv_count = len(state.get("ohlcv_bars", []))
    fred_ids = [s["series_id"] for s in state.get("fred_series", [])]
    asset_names = [a["name"] for a in state.get("related_assets", [])]
    news_articles = state.get("news_articles", [])
    news_sources: Dict[str, int] = {}
    for a in news_articles:
        src = a.get("source", "unknown")
        news_sources[src] = news_sources.get(src, 0) + 1
    news_summary = (
        ", ".join(f"{k}={v}" for k, v in news_sources.items())
        if news_sources else "없음"
    )
    gpr_count = len(state.get("gpr_observations", []))

    return (
        f"분석 대상: {ticker} | 기간: {start} ~ {end}\n\n"
        f"수집된 데이터 요약:\n"
        f"- OHLCV 데이터: {ohlcv_count}개 거래일\n"
        f"- FRED 경제지표: {', '.join(fred_ids) if fred_ids else '없음'}\n"
        f"- 연관 자산: {', '.join(asset_names) if asset_names else '없음'}\n"
        f"- 뉴스 기사: {len(news_articles)}건 ({news_summary})\n"
        f"- GPR 지수 관측치: {gpr_count}건\n\n"
        "도구를 호출해 데이터를 탐색하고 가설을 생성하십시오."
    )


def _parse_hypotheses(text: str) -> List[Dict[str, Any]]:
    try:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            raise ValueError("JSON 배열 없음")
        return json.loads(text[start:end])
    except Exception as exc:
        logger.warning("[GenerateHypotheses] JSON 파싱 실패: %s | raw=%s", exc, text[:200])
        return []


async def generate_hypotheses(state: CausalityAgentState) -> Dict[str, Any]:
    """LangChain Tool Use 루프로 투자 가설을 생성한다."""
    errors: List[str] = list(state.get("errors", []))
    tool_call_log: List[str] = []

    tools = make_langchain_tools(state)
    llm = get_workflow_llm(model=_MODEL).bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=_build_context_message(state)),
    ]

    hypotheses: List[Dict[str, Any]] = []

    logger.info("[CausalityAgent] [3/3] 가설 생성 시작 (최대 %d 라운드)", _MAX_TOOL_ROUNDS)
    for round_idx in range(_MAX_TOOL_ROUNDS):
        response = await llm.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            hypotheses = _parse_hypotheses(response.content)
            logger.info(
                "[CausalityAgent] [3/3] 완료: round=%d, hypotheses=%d, tools=%s",
                round_idx + 1,
                len(hypotheses),
                tool_call_log,
            )
            break

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_call_log.append(tool_name)
            logger.info("[CausalityAgent]   └ [round %d] 도구 호출: %s", round_idx + 1, tool_name)

            tool = tool_map.get(tool_name)
            if tool is None:
                result = json.dumps({"error": f"알 수 없는 도구: {tool_name}"})
            else:
                try:
                    result = tool.invoke(tc["args"])
                except Exception as exc:
                    result = json.dumps({"error": str(exc)})

            logger.debug("[GenerateHypotheses] %s(%s) → %s", tool_name, tc["args"], str(result)[:120])
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    else:
        errors.append(f"Tool Use 최대 라운드({_MAX_TOOL_ROUNDS}) 도달, 가설 미완성")
        logger.warning("[CausalityAgent] [3/3] 최대 라운드 도달, 가설 미완성")

    unique_tools = list(dict.fromkeys(tool_call_log))
    for h in hypotheses:
        if not h.get("supporting_tools_called"):
            h["supporting_tools_called"] = unique_tools

    return {
        "hypotheses": hypotheses,
        "tool_call_log": tool_call_log,
        "errors": errors,
    }
