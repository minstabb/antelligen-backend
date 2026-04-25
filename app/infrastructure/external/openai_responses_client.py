import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from openai import OpenAI

from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OpenAIResponsesResult:
    output_text: str
    model: str


class OpenAIResponsesClient:
    """OpenAI Responses API (gpt-5-mini) 공용 External Client.

    Infrastructure Layer 규칙에 따라 기술 세부사항(OpenAI SDK 초기화, API 호출)을
    이 모듈에서 관리한다. Application / Adapter 는 이 클라이언트를 직접 호출하지 않고
    도메인별 Outbound Adapter 를 통해 간접적으로 이용한다.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        request_timeout: float = 90.0,
    ):
        # OpenAI SDK 전역 timeout — 네트워크/reasoning hang 방어
        self._client = OpenAI(api_key=api_key, timeout=request_timeout)
        self._model = model
        self._request_timeout = request_timeout

    async def create(
        self,
        instructions: str,
        input_text: str,
        model: Optional[str] = None,
        text_format: Optional[Dict[str, Any]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> OpenAIResponsesResult:
        used_model = model or self._model
        effective_timeout = timeout if timeout is not None else self._request_timeout
        print(
            f"[openai.responses] 요청 model={used_model} input_len={len(input_text)} "
            f"text_format={'on' if text_format else 'off'} "
            f"max_out={max_output_tokens or 'default'} "
            f"reasoning={(reasoning or {}).get('effort') or 'default'} "
            f"timeout={effective_timeout}s"
        )
        logger.debug("[openai.responses] model=%s input_len=%d", used_model, len(input_text))

        kwargs: Dict[str, Any] = {
            "model": used_model,
            "instructions": instructions,
            "input": input_text,
        }
        if text_format is not None:
            kwargs["text"] = {"format": text_format}
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        if reasoning is not None:
            kwargs["reasoning"] = reasoning

        # asyncio.wait_for 로 thread 작업 자체에 상한 설정 (SDK timeout 이 무시되는 edge 방어)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.with_options(timeout=effective_timeout).responses.create,
                    **kwargs,
                ),
                timeout=effective_timeout + 5.0,
            )
        except asyncio.TimeoutError as exc:
            print(f"[openai.responses] ⏱ timeout model={used_model} after {effective_timeout}s")
            raise TimeoutError(
                f"OpenAI Responses API timeout after {effective_timeout}s"
            ) from exc

        output_text = getattr(response, "output_text", "") or ""
        print(
            f"[openai.responses] 응답 수신 model={used_model} output_len={len(output_text)}"
        )
        return OpenAIResponsesResult(output_text=output_text, model=used_model)


_singleton: Optional[OpenAIResponsesClient] = None


def get_openai_responses_client() -> OpenAIResponsesClient:
    global _singleton
    if _singleton is None:
        settings = get_settings()
        _singleton = OpenAIResponsesClient(
            api_key=settings.openai_api_key,
            model=settings.openai_learning_model,
        )
    return _singleton
