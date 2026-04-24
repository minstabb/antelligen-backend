"""OpenAI Responses API 기반 경제 일정 영향 분석 어댑터.

입력: 경제 일정 + 매크로 지표 스냅샷
출력: summary / direction / impact_tags / key_drivers / risks (JSON schema 강제)
"""

import json
import logging
import re
from typing import Any, Dict, List

from app.domains.schedule.application.port.out.event_impact_analyzer_port import (
    EventImpactAnalysisResult,
    EventImpactAnalyzerPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.infrastructure.external.openai_responses_client import OpenAIResponsesClient

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "당신은 Antelligen AI 매크로 리서치 데스크의 시니어 전략 애널리스트입니다.\n"
    "기관 투자자 브리핑 수준의 절제된 한국어 존댓말로, 주어진 경제 일정(또는 '일일 매크로 "
    "스냅샷' 형태의 종합 분석 요청)을 받아 시장에 미칠 영향을 구조화된 JSON 으로 답변합니다.\n"
    "\n"
    "분석 필수 커버리지(빠뜨리지 말 것):\n"
    "1) 현재 진행 중이거나 최근 전개된 **지정학 이벤트**(전쟁·무력 충돌·제재·OPEC 결정·"
    "   주요국 선거·무역 분쟁 등)가 존재하면 그 이벤트가 유발/증폭하는 매크로 변수 움직임을 "
    "   반드시 언급합니다. 당신이 알고 있는 최신 지식을 활용하되, 단정적 선언 대신 "
    "   '~이 지속되고 있다고 알려져 있으며' 같은 절제된 표현을 씁니다.\n"
    "2) 핵심 매크로 변수 — 미국 2년물/10년물/20년물 금리, DXY, USD/KRW, USD/JPY, VIX, "
    "   WTI, 금, 크레딧 스프레드 — 가 어떻게 움직였거나 움직일 여지가 있는지 구체적으로 "
    "   서술합니다.\n"
    "3) 위험자산(특히 **코스피·코스피200·나스닥·나스닥100·S&P500**)에 미치는 파급 효과를 "
    "   반드시 한 번 이상 언급합니다. 외국인 수급·원화 변동성·반도체 경기 등 한국 특유 채널도 "
    "   고려합니다.\n"
    "4) 안전자산 선호 변화(금, 미국채, 엔화) 방향도 필요한 경우 함께 짚습니다.\n"
    "\n"
    "출력 규칙:\n"
    "- summary: 한국어 4~6문장. 결론만 반복하지 말고 지정학 맥락 → 매크로 변수 변화 → "
    "  위험자산 파급 순으로 자연스럽게 이어갑니다.\n"
    "- direction: 'bullish' | 'bearish' | 'neutral' | 'mixed' 중 하나.\n"
    "- impact_tags: 3~5개 단어형 태그 (예: 지정학, 전쟁, 유가, 인플레이션, 달러강세, "
    "  안전자산, 코스피, 나스닥, 반도체, 금리, 수급 등).\n"
    "- key_drivers: 3~4개 문장형 핵심 드라이버. 각 드라이버는 특정 지표/자산명과 함께 작성.\n"
    "- risks: 2~3개 문장형 반증·리스크 요인 (예: 휴전 타결 시 유가 급락, VIX 급등 시 "
    "  크로스에셋 동반 하락 등).\n"
    "- 특정 유튜브 채널·영상·인물·외부 리서치 기관명은 노출하지 마십시오.\n"
    "- 'Antelligen AI' 브랜드는 전체에서 최대 1회까지만 자연스럽게 사용합니다.\n"
    "- 모든 문장은 '~입니다', '~습니다', '~됩니다' 등 존댓말 종결을 사용합니다.\n"
    "- 숫자 레벨(예: 코스피200 930, S&P500 5800, VIX 18, DXY 105, WTI 82)은 반드시 "
    "  해당 지수·자산명을 앞에 붙입니다. 단, %·bp·배수 단위는 지수명 생략 허용.\n"
    "- 한글·영문 혼용 금지: 하나의 단어 안에서 한글과 영문 알파벳을 섞지 마십시오. "
    "  영어 용어는 원문 영문 그대로(follow-through, breadth, breakout, invalidation, "
    "  rollover, contango, basis) 쓰거나 완전한 한글 음차(팔로스루, 브레드스)로 "
    "  일관 표기합니다. '포ollow-through', '브레ket' 같은 하이브리드 표기 절대 금지.\n"
    "\n"
    "반드시 JSON 스키마에 맞춰 답변하고, 코드펜스·마크다운·설명 문구를 포함하지 마십시오.\n"
)

_JSON_SCHEMA = {
    "type": "json_schema",
    "name": "event_impact_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "direction", "impact_tags", "key_drivers", "risks"],
        "properties": {
            "summary": {"type": "string"},
            "direction": {
                "type": "string",
                "enum": ["bullish", "bearish", "neutral", "mixed"],
            },
            "impact_tags": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {"type": "string"},
            },
            "key_drivers": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"type": "string"},
            },
            "risks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "string"},
            },
        },
    },
}


class OpenAIEventImpactAnalyzer(EventImpactAnalyzerPort):
    def __init__(self, client: OpenAIResponsesClient):
        self._client = client
        self._model = getattr(client, "_model", "gpt-5-mini")

    async def analyze(
        self,
        event: EconomicEvent,
        indicator_snapshot: Dict[str, Any],
    ) -> EventImpactAnalysisResult:
        input_text = self._build_input(event, indicator_snapshot)
        print(
            f"[schedule.analyzer] 요청 event_id={event.id} title={event.title[:30]!r} "
            f"indicators={len(indicator_snapshot)}"
        )
        result = await self._client.create(
            instructions=_INSTRUCTIONS,
            input_text=input_text,
            text_format=_JSON_SCHEMA,
            max_output_tokens=1500,
            reasoning={"effort": "low"},
            timeout=90.0,
        )
        print(
            f"[schedule.analyzer] 응답 event_id={event.id} raw_len={len(result.output_text)}"
        )
        parsed = self._parse(result.output_text)
        return parsed

    @staticmethod
    def _build_input(event: EconomicEvent, snapshot: Dict[str, Any]) -> str:
        event_section = (
            f"[경제 일정]\n"
            f"- 제목: {event.title}\n"
            f"- 일시: {event.event_at.isoformat()}\n"
            f"- 국가: {event.country}\n"
            f"- 중요도: {event.importance.value}\n"
            f"- 출처: {event.source}"
        )

        lines = []
        for key, info in snapshot.items():
            if not isinstance(info, dict):
                continue
            display = info.get("display_name") or key
            value = info.get("value")
            unit = info.get("unit", "")
            lines.append(f"- {display}: {value} {unit}".strip())
        snapshot_section = "\n".join(lines) or "- (지표 스냅샷 없음)"

        is_snapshot = (event.source or "").lower() == "snapshot"
        if is_snapshot:
            guidance = (
                "[지시] 오늘은 별도로 예정된 주요 경제 일정이 없는 날입니다. "
                "대신 **현재 진행 중인 지정학 이벤트**(전쟁·무력 충돌·제재·OPEC 결정·"
                "주요국 정치 이벤트 등)와 최근 매크로 흐름을 종합해, 핵심 매크로 변수(금리·"
                "유가·환율·VIX·DXY·금)가 어떻게 반응했는지, 그리고 그것이 **코스피·코스피200"
                "·나스닥·나스닥100·S&P500** 등 위험자산에 미친/미칠 영향을 분석하십시오. "
                "'예정된 일정이 없어 분석할 것이 없다' 같은 회피성 응답은 금지합니다. "
                "반드시 위의 지정학·매크로·위험자산 3단 논리로 설명하고 JSON 으로만 답변하십시오."
            )
        else:
            guidance = (
                "[지시] 위 경제 일정이 한국 시장 및 글로벌 자산군(주식·채권·환율·원자재)에 "
                "미칠 수 있는 잠재 영향을 분석하십시오. 현재 진행 중인 지정학 이벤트가 있다면 "
                "함께 고려하고, **코스피·코스피200·나스닥·나스닥100·S&P500** 등 위험자산에 "
                "미치는 영향을 반드시 한 번 이상 언급하여 JSON 으로만 답변하십시오."
            )

        return (
            f"{event_section}\n\n"
            f"[현재 매크로 지표 스냅샷]\n{snapshot_section}\n\n"
            f"{guidance}"
        )

    @staticmethod
    def _parse(raw: str) -> EventImpactAnalysisResult:
        text = (raw or "").strip()
        payload: Dict[str, Any] = {}
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    try:
                        payload = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        logger.warning("[schedule.analyzer] JSON 파싱 실패: %s", text[:200])

        def _as_list(key: str) -> List[str]:
            items = payload.get(key) or []
            if not isinstance(items, list):
                return []
            return [str(i).strip() for i in items if str(i).strip()]

        return EventImpactAnalysisResult(
            summary=str(payload.get("summary") or "").strip(),
            direction=str(payload.get("direction") or "neutral").strip().lower(),
            impact_tags=_as_list("impact_tags"),
            key_drivers=_as_list("key_drivers"),
            risks=_as_list("risks"),
        )
