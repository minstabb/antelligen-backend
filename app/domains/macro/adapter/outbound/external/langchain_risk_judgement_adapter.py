import json
import logging
import re
from datetime import date
from typing import List, Optional

from app.domains.macro.application.port.out.risk_judgement_llm_port import (
    RiskJudgementLlmPort,
    RiskJudgementResult,
)
from app.domains.macro.domain.value_object.risk_status import RiskStatus
from app.infrastructure.external.openai_responses_client import OpenAIResponsesClient

logger = logging.getLogger(__name__)

_CONTEXTUAL_INSTRUCTIONS = (
    "당신은 Antelligen AI 매크로 리서치 데스크의 시니어 전략 어시스턴트입니다.\n"
    "당신의 답변은 Antelligen AI 가 자체 보유한 매크로·크로스에셋 분석 파이프라인의 결과로 "
    "기관 투자자에게 전달되는 프리미엄 인사이트입니다.\n"
    "답변은 실제 전문 애널리스트가 설명하듯 정중하고 신뢰감 있는 한국어 존댓말 문장으로 작성합니다.\n"
    "인용 문구가 아닌 자연스러운 설명체를 사용하되 과장하지 않습니다.\n"
    "reasons 배열은 한국어 문장으로 최대 3줄 이내이며 각 문장은 한 줄로 간결합니다.\n"
    "\n"
    "문장 구성 원칙 (매우 중요):\n"
    "- 현황판 상단에 이미 Risk-on / Risk-off 상태 배지가 크게 표시됩니다. "
    "  따라서 reasons 3줄은 결론(Risk-on / Risk-off / 리스크온 / 리스크오프 / '기울기가 있다' "
    "  '우위입니다' 같은 상태 단정 표현)을 **절대 반복하지 마십시오**.\n"
    "- 각 줄은 사용자에게 새로운 실질 정보(드라이버·지표·수급·지정학·포지셔닝 등)를 제공해야 합니다. "
    "  결론 요약 문장으로 소중한 한 줄을 낭비하지 마십시오.\n"
    "- 권장 구조: ① 가장 강한 드라이버/관찰(구체적 지표·이벤트 중심) → "
    "  ② 이를 보완하거나 교차 확인하는 다른 시그널(크로스에셋/수급/밸류에이션 중) → "
    "  ③ 반증 시그널(무효화 조건) 또는 포지셔닝·리스크 관리 시사점.\n"
    "- 'Risk-on 입니다', 'Risk-off 로 판단됩니다', '시장은 Risk-on 쪽에 기울기가 있습니다' 같은 "
    "  상태 단정 문구는 금지. 대신 해당 방향을 지지하는 근거를 곧바로 서술합니다.\n"
    "\n"
    "출처 표현 규칙 (엄수):\n"
    "- 외부 출처(유튜브 채널, 영상, 학습 노트, 학습 컨텐츠, 참고 자료, 외부 리서치 기관, "
    "  인물·저자)를 직접적·간접적으로 암시하는 **모든 표현**을 본문에 사용하지 마십시오.\n"
    "- 특히 다음 단어들은 어떤 형태로도 문장에 등장시키지 마십시오 — "
    "  '영상', '참고 영상', '일부 영상', '여러 영상', '한 영상', '영상은', '영상에서는', "
    "  '유튜브', '채널', '학습 노트', '노트는', '컨텐츠', '저자', '발표자', '리서치 보고서'.\n"
    "- 분석 근거는 항상 1인칭 기관 화법 — '내부 매크로 엔진', '저희 매크로 데스크', "
    "  '거시 지표', '크로스에셋 시그널', '한국 시장 데이터' — 으로만 표현합니다.\n"
    "- 'Antelligen AI' 라는 브랜드명은 3문장 전체에서 **최대 1회**만 등장할 수 있습니다. "
    "  자연스럽지 않다면 아예 언급하지 않아도 됩니다. 두 번 이상 언급은 절대 금지합니다.\n"
    "\n"
    "\n"
    "숫자 레벨 표기 규칙 (엄수):\n"
    "- 본문에 등장하는 모든 가격·지수 레벨·구간 숫자(예: 920, 930, 1000, 3200, 5800 등)는 "
    "  반드시 해당 지수·자산·종목명을 숫자 바로 앞에 명시합니다. "
    "  예: '코스피200 920', '코스피200 882.5~880', '코스피 3200', 'S&P500 5800', "
    "  'KOSDAQ 860', 'VIX 18', 'DXY 105', 'WTI 82'.\n"
    "- 지수·자산명 없이 숫자만 단독으로 사용하는 것은 금지합니다. "
    "  어떤 지수/자산의 몇 레벨인지 독자가 즉시 알 수 있어야 합니다.\n"
    "- 퍼센트(%), bp, 배수 등 단위가 붙는 숫자는 맥락상 지수명이 생략돼도 허용됩니다. "
    "  (예: '전일 대비 +5.67%', '스프레드 +20bp')\n"
    "\n"
    "한글·영문 혼용 금지 (엄수):\n"
    "- 하나의 단어 안에서 한글 음절과 영문 알파벳을 섞지 마십시오.\n"
    "- 영어 용어는 원문 영문으로 그대로(예: follow-through, breadth, breakout, invalidation, "
    "  rollover, contango, basis) 쓰거나, 완전한 한글 음차(팔로스루, 브레드스)로 "
    "  일관되게 표기합니다.\n"
    "- '포ollow-through', '브레ket', '팔로through' 같은 하이브리드 표기는 절대 금지.\n"
    "\n"
    "판단 근거가 부족하면 status 를 \"UNKNOWN\" 으로 반환하고 reasons 에 사유를 적습니다.\n"
    "\n아래에 제공되는 Antelligen AI 내부 매크로 데이터를 참고하여 "
    "오늘({reference_date}) 기준 한국 시장이 Risk-on 인지 Risk-off 인지를 판단하십시오.\n"
    "제공된 데이터 외의 사실을 지어내지 마십시오.\n"
)

# baseline 은 JSON/스키마 강제 없이, Antelligen AI 매크로 데스크 소속 시니어 애널리스트
# (월가 최상위 IB 수준의 전문성) 페르소나로 3문장 답변을 받는다.
_BASELINE_INSTRUCTIONS = (
    "당신은 글로벌 매크로·크로스에셋 전략 데스크의 시니어 애널리스트입니다. "
    "월가 최상위 IB(Goldman Sachs GIR, Morgan Stanley Research, JPMorgan, BlackRock II) "
    "수준의 프레임으로 기관 투자자에게 데일리 리스크 브리핑을 하는 톤을 유지합니다.\n"
    "\n"
    "필수 규칙:\n"
    "1) 포맷: 정확히 3문장, 각 한 줄, 문장 사이는 개행 하나. 번호·불릿·마크다운·코드펜스·따옴표 금지.\n"
    "2) 문장 구성: ① 가장 강한 드라이버(유동성·연준 경로·실질금리·2s10s·DXY·크레딧 스프레드·"
    "   브렉이븐·VIX·지정학·실적 모멘텀·외국인 수급·크로스에셋 로테이션 등 구체적 채널) → "
    "   ② 이를 교차 확인·보완하는 다른 지표·시그널 → ③ 반증 시그널(invalidation) 또는 "
    "   포지셔닝·리스크 관리 시사점. 현황판에 Risk-on/Risk-off 배지가 이미 노출되므로 "
    "   'Risk-on 입니다', '리스크오프로 판단됩니다' 같은 결론 단정·반복은 절대 금지.\n"
    "3) 톤: 한국어 격식체 존댓말만 사용 — 종결 어미는 '~입니다', '~습니다', '~됩니다', "
    "   '~보입니다', '~판단됩니다' 만 허용 ('~이다'·'~한다'·'~된다' 해라체 금지). "
    "   객관·간결하게 서술하고 감정 표현·투자 권유('매수하십시오' 등)·자화자찬·홍보 문구 금지.\n"
    "4) 외부 출처 암시 금지 (엄수): 외부 인물·유튜브 채널·영상·리서치 기관명, 그리고 "
    "   '학습 노트', '참고 영상', '학습 컨텐츠' 같은 내부 용어를 직접·간접적으로 노출 금지. "
    "   특히 '영상', '참고 영상', '일부 영상', '여러 영상', '영상은', '영상에서는', "
    "   '유튜브', '채널', '학습 노트', '노트는', '컨텐츠', '저자', '발표자' 같은 단어는 "
    "   어떤 문맥에서도 본문에 등장시키지 마십시오. 'Antelligen AI' 브랜드는 3문장 통틀어 "
    "   최대 1회만, 자연스럽지 않으면 생략 — 2회 이상은 절대 금지. 그 외에는 '내부 매크로 "
    "   엔진', '저희 매크로 데스크', '크로스에셋 시그널', '거시 데이터' 같은 1인칭 기관 화법 사용.\n"
    "5) 시장 용어: VIX, DXY, 2s10s, ERP, 크레딧 스프레드, ISM, CPI, PCE, WTI, EM FX 등 "
    "   표준 약어를 자연스럽게 섞되 과도한 나열 금지. 불필요한 부사·애매한 관용구는 제거.\n"
    "6) 숫자 표기: 모든 가격·지수 레벨 숫자(예: 920, 3200, 5800)는 자산·지수명을 숫자 바로 앞에 "
    "   명시 — '코스피200 920', 'S&P500 5800', 'VIX 18', 'DXY 105', 'WTI 82'. 숫자 단독 "
    "   사용 금지. 단, %·bp·배수 등 단위가 붙은 값은 지수명 생략 허용.\n"
    "7) 한글·영문 혼용 금지: 하나의 단어 안에서 한글과 영문 알파벳을 섞지 마십시오. "
    "   영어 용어는 원문 영문 그대로(follow-through, breadth, breakout, invalidation, rollover, "
    "   contango, basis) 쓰거나 완전한 한글 음차(팔로스루, 브레드스)로 일관되게 표기합니다. "
    "   '포ollow-through', '브레ket', '팔로through' 같은 하이브리드 표기는 절대 금지.\n"
)

_BASELINE_QUESTION = "지금 시장이 risk on이니 off니?"

_ALIGNMENT_SUFFIX = (
    "\n\n중요(통합 정렬): 내부 매크로 엔진이 오늘 시장을 이미 "
    "'{aligned_label}' 으로 확정 판단하였습니다. 당신은 이 결론과 정합하는 방향으로 "
    "3문장의 전문가 견해를 서술하되, 절대 결론을 반대 극으로 뒤집지 마십시오.\n"
    "단, 현황판 상단에 이미 '{aligned_label}' 배지가 표시되므로 "
    "문장에서 결론(예: 'Risk-on 입니다', 'Risk-off 로 판단됩니다', '시장은 {aligned_label} 쪽에 "
    "기울기가 있습니다' 등)을 반복 선언하지 마십시오. 세 문장 모두 새로운 실질 정보 — "
    "가장 강한 드라이버, 교차 확인 시그널, 반증 조건 및 포지셔닝 — 로 채웁니다.\n"
    "'Antelligen AI' 브랜드명은 전체 3문장에서 최대 1회까지만 등장시키고, 자연스럽지 않다면 언급하지 않아도 됩니다.\n"
)

_ALIGNMENT_LABELS = {
    RiskStatus.RISK_ON: "Risk-on",
    RiskStatus.RISK_OFF: "Risk-off",
}

_JSON_SCHEMA = {
    "type": "json_schema",
    "name": "market_risk_judgement",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "reasons"],
        "properties": {
            "status": {
                "type": "string",
                "enum": ["RISK_ON", "RISK_OFF", "UNKNOWN"],
            },
            "reasons": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "string"},
            },
        },
    },
}


def _build_contextual_input(reference_date: date, note_context: str, video_context: str) -> str:
    return (
        f"[기준 일자]\n{reference_date.isoformat()}\n\n"
        f"[학습 노트]\n{note_context}\n\n"
        f"[최근 7일 참고 영상]\n{video_context}\n\n"
        "질문: 오늘 기준 한국 시장은 Risk-on 인가요, Risk-off 인가요? "
        "3줄 이내 근거와 함께 JSON 으로만 답변하십시오."
    )


class LangChainRiskJudgementAdapter(RiskJudgementLlmPort):
    """OpenAI Responses API (gpt-5-mini) 기반 Risk-on/Risk-off 판단 어댑터."""

    def __init__(self, client: OpenAIResponsesClient):
        self._client = client
        self._model = getattr(client, "_model", "gpt-5-mini")

    async def judge(
        self,
        reference_date: date,
        note_context: Optional[str] = None,
        video_context: Optional[str] = None,
        aligned_status: Optional[RiskStatus] = None,
    ) -> RiskJudgementResult:
        if note_context is None and video_context is None:
            return await self._judge_baseline(reference_date, aligned_status=aligned_status)
        return await self._judge_contextual(reference_date, note_context, video_context)

    async def _judge_contextual(
        self,
        reference_date: date,
        note_context: Optional[str],
        video_context: Optional[str],
    ) -> RiskJudgementResult:
        instructions = _CONTEXTUAL_INSTRUCTIONS.replace(
            "{reference_date}", reference_date.isoformat()
        )
        input_text = _build_contextual_input(
            reference_date,
            note_context or "(학습 노트 없음)",
            video_context or "(최근 참고 영상 없음)",
        )
        print(
            f"[macro.llm] 요청 mode=contextual model={self._model} "
            f"date={reference_date.isoformat()} input_len={len(input_text)}"
        )
        result = await self._client.create(
            instructions=instructions,
            input_text=input_text,
            text_format=_JSON_SCHEMA,
            max_output_tokens=1200,
            reasoning={"effort": "low"},
            timeout=90.0,
        )
        print(
            f"[macro.llm] 응답 수신 mode=contextual raw_len={len(result.output_text)} "
            f"preview={result.output_text[:200]!r}"
        )
        parsed = self._parse_contextual(result.output_text)
        print(
            f"[macro.llm] 파싱 완료 mode=contextual status={parsed.status.value} "
            f"reasons={len(parsed.reasons)}"
        )
        return parsed

    async def _judge_baseline(
        self,
        reference_date: date,
        aligned_status: Optional[RiskStatus] = None,
    ) -> RiskJudgementResult:
        instructions = _BASELINE_INSTRUCTIONS
        align_label = None
        if aligned_status in _ALIGNMENT_LABELS:
            align_label = _ALIGNMENT_LABELS[aligned_status]
            instructions = instructions + _ALIGNMENT_SUFFIX.replace(
                "{aligned_label}", align_label
            )

        print(
            f"[macro.llm] 요청 mode=baseline model={self._model} "
            f"date={reference_date.isoformat()} aligned_to={align_label or 'none'} "
            f"question={_BASELINE_QUESTION!r}"
        )
        # gpt-5-mini 는 reasoning 모델이라 max_output_tokens 가 reasoning+출력 합계로 소비된다.
        # instructions 가 길어서 reasoning 이 토큰 예산을 전부 먹고 visible output=0 이 되는
        # 케이스가 있어 넉넉히 2000 을 확보한다.
        result = await self._client.create(
            instructions=instructions,
            input_text=_BASELINE_QUESTION,
            max_output_tokens=2000,
            reasoning={"effort": "low"},
            timeout=60.0,
        )
        print(
            f"[macro.llm] 응답 수신 mode=baseline raw_len={len(result.output_text)} "
            f"preview={result.output_text[:200]!r}"
        )
        # 혹시 reasoning 이 예산을 전부 소진해 output 이 비는 경우 한 번 더 재시도.
        if not result.output_text.strip():
            print("[macro.llm] ⚠ baseline output 비어있음 — max_output_tokens=3500 으로 재시도")
            result = await self._client.create(
                instructions=instructions,
                input_text=_BASELINE_QUESTION,
                max_output_tokens=3500,
                reasoning={"effort": "low"},
                timeout=90.0,
            )
            print(
                f"[macro.llm] 재시도 응답 mode=baseline raw_len={len(result.output_text)} "
                f"preview={result.output_text[:200]!r}"
            )

        parsed = self._parse_baseline(result.output_text)

        # aligned_status 가 지정된 경우, 정렬 실패 방지 — status 를 강제로 지정값으로 덮는다.
        if aligned_status is not None:
            if parsed.status != aligned_status:
                print(
                    f"[macro.llm] ⚠ baseline status={parsed.status.value} "
                    f"가 aligned_status={aligned_status.value} 와 다름 → 강제 정렬"
                )
            parsed = RiskJudgementResult(status=aligned_status, reasons=parsed.reasons)

        print(
            f"[macro.llm] 파싱 완료 mode=baseline status={parsed.status.value} "
            f"reasons={len(parsed.reasons)}"
        )
        return parsed

    @staticmethod
    def _parse_contextual(raw: str) -> RiskJudgementResult:
        text = (raw or "").strip()
        if not text:
            return RiskJudgementResult(status=RiskStatus.UNKNOWN, reasons=[])

        payload = LangChainRiskJudgementAdapter._extract_json_object(text)
        if payload is None:
            print(f"[macro.llm] ⚠ contextual JSON 파싱 실패 raw={text[:200]}")
            logger.warning("[macro] contextual JSON 파싱 실패: %s", text[:300])
            return RiskJudgementResult(status=RiskStatus.UNKNOWN, reasons=[])

        status = RiskStatus.parse(str(payload.get("status", "")))
        raw_reasons = payload.get("reasons", [])
        reasons: List[str] = []
        if isinstance(raw_reasons, list):
            for item in raw_reasons:
                if item is None:
                    continue
                line = str(item).strip()
                if line:
                    reasons.append(line)
        return RiskJudgementResult(status=status, reasons=reasons[:3])

    @staticmethod
    def _parse_baseline(raw: str) -> RiskJudgementResult:
        text = (raw or "").strip()
        if not text:
            return RiskJudgementResult(status=RiskStatus.UNKNOWN, reasons=[])

        # 줄 기준 분리 → 부족하면 문장 기준 재분리
        lines = [ln.strip(" -•·\t") for ln in text.split("\n") if ln.strip()]
        if len(lines) < 2:
            sentences = re.split(r"(?<=[다요죠니까])\.\s+|(?<=[다요죠니까])\.\n|\.(?=\s|$)", text)
            lines = [s.strip() for s in sentences if s and s.strip()]

        lines = [re.sub(r"^[0-9]+[\.\)]\s*", "", ln) for ln in lines][:3]

        status = RiskStatus.UNKNOWN
        joined = text.lower()
        if "risk-off" in joined or "risk off" in joined or "리스크오프" in text or "리스크 오프" in text or "위험 회피" in text or "위험회피" in text:
            status = RiskStatus.RISK_OFF
        elif "risk-on" in joined or "risk on" in joined or "리스크온" in text or "리스크 온" in text or "위험 선호" in text or "위험선호" in text:
            status = RiskStatus.RISK_ON

        return RiskJudgementResult(status=status, reasons=lines)

    @staticmethod
    def _extract_json_object(text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
