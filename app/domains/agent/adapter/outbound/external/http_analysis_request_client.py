from typing import Any

import httpx
from pydantic import ValidationError

from app.common.exception.app_exception import AppException
from app.domains.agent.application.port.analysis_request_client import (
    AnalysisRequestClient,
)
from app.domains.agent.application.request.finance_analysis_request import (
    FinanceAnalysisRequest,
)
from app.domains.agent.application.response.frontend_agent_response import (
    FrontendAgentResponse,
)


class HttpAnalysisRequestClient(AnalysisRequestClient):
    def __init__(self, finance_analysis_url: str | None, timeout_seconds: float = 10.0):
        self._finance_analysis_url = finance_analysis_url.rstrip("/") if finance_analysis_url else None
        self._timeout_seconds = timeout_seconds

    async def request_finance_analysis(
        self,
        request: FinanceAnalysisRequest,
        authorization: str | None = None,
    ) -> FrontendAgentResponse:
        if not self._finance_analysis_url:
            raise AppException(
                status_code=503,
                message="분석 API 서버 주소가 설정되지 않았습니다.",
            )

        headers = {"Content-Type": "application/json"}
        if authorization:
            headers["Authorization"] = authorization

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    self._finance_analysis_url,
                    json=request.model_dump(exclude_none=True),
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise AppException(
                status_code=504,
                message="분석 API 서버 응답이 지연되고 있습니다.",
            ) from exc
        except httpx.RequestError as exc:
            raise AppException(
                status_code=502,
                message="분석 API 서버에 연결할 수 없습니다.",
            ) from exc

        payload = self._parse_payload(response)

        if response.status_code >= 500:
            raise AppException(
                status_code=502,
                message=f"분석 API 서버 오류: {self._extract_message(payload)}",
            )

        if response.status_code >= 400:
            raise AppException(
                status_code=response.status_code,
                message=self._extract_message(payload),
            )

        if isinstance(payload, dict) and payload.get("success") is False:
            raise AppException(
                status_code=502,
                message=self._extract_message(payload),
            )

        data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

        try:
            return FrontendAgentResponse.model_validate(data)
        except ValidationError as exc:
            raise AppException(
                status_code=502,
                message="분석 API 서버 응답 형식이 올바르지 않습니다.",
            ) from exc

    def _parse_payload(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise AppException(
                status_code=502,
                message="분석 API 서버 응답을 해석할 수 없습니다.",
            ) from exc

    def _extract_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("message", "detail", "error_message", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return "분석 요청 처리 중 오류가 발생했습니다."
