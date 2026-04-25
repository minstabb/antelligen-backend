import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.domains.company_profile.application.port.out.business_overview_port import (
    BusinessOverviewPort,
)
from app.domains.company_profile.domain.value_object.business_overview import BusinessOverview
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 한국 상장기업 분석가입니다.
주어진 정보를 바탕으로 해당 기업의 사업 내용과 주요 매출원을 한국어로 정리하세요.

**규칙**:
- summary 는 2~3 문장. 무엇을 만들고/판매하는 회사인지 핵심만.
- revenue_sources 는 3~5 개의 짧은 항목 (예: "DRAM 메모리", "스마트폰 사업", "콘텐츠 IP 라이선싱").
- 각 항목은 15자 이내, 비중·연도·수치는 빼고 사업 부문/제품/서비스명만.
- 추측이 어려우면 일반적인 업종 특성으로 합리적으로 작성.
- 마크다운 금지. 반드시 아래 JSON 형식만 반환.

```json
{
  "summary": "<2~3 문장 한국어 사업 요약>",
  "revenue_sources": ["<항목1>", "<항목2>", "..."]
}
```"""


class OpenAIBusinessOverviewClient(BusinessOverviewPort):
    """gpt-5-mini 로 사업 개요 + 매출원을 추출하는 어댑터.

    rag_context 가 주어지면 사업보고서 발췌를 컨텍스트로 사용하고,
    없으면 기업명과 업종코드만으로 일반 지식 기반 요약을 생성한다.
    """

    async def generate(
        self,
        corp_name: str,
        induty_code: Optional[str],
        rag_context: Optional[str],
    ) -> Optional[BusinessOverview]:
        settings = get_settings()
        if not settings.openai_api_key:
            logger.warning("[BusinessOverview] OPENAI_API_KEY 없음 — 생성 불가")
            return None

        user_prompt = _build_user_prompt(corp_name, induty_code, rag_context)
        source = "rag_summary" if rag_context else "llm_only"

        try:
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model=settings.openai_finance_agent_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            data = json.loads(raw.strip())
        except Exception as e:
            logger.warning("[BusinessOverview] LLM 호출 실패 corp_name=%s: %s", corp_name, e)
            return None

        summary = (data.get("summary") or "").strip()
        if not summary:
            return None

        sources = data.get("revenue_sources") or []
        revenue_sources = [s.strip() for s in sources if isinstance(s, str) and s.strip()][:5]

        return BusinessOverview(
            summary=summary,
            revenue_sources=revenue_sources,
            source=source,
        )


def _build_user_prompt(
    corp_name: str,
    induty_code: Optional[str],
    rag_context: Optional[str],
) -> str:
    parts = [f"[기업명] {corp_name}"]
    if induty_code:
        parts.append(f"[업종코드] {induty_code}")
    if rag_context:
        # 컨텍스트 길이 상한 — 토큰 비용 보호
        truncated = rag_context[:3000]
        parts.append(f"[사업보고서 발췌]\n{truncated}")
    else:
        parts.append("[참고] 사업보고서 발췌가 없으므로 일반 지식으로 추정 작성하세요.")
    return "\n\n".join(parts)
