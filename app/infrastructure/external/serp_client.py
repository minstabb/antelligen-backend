"""
SERP API 공용 HTTP 클라이언트 (Infrastructure Layer)

- 모든 SERP API 호출을 단일 클라이언트로 통합
- 재시도 (지수 백오프, 최대 3회)
- 구조화된 로깅 (요청/응답/오류)
- 타임아웃 및 네트워크 오류 처리
- 스모크 호출(ping) 경로 제공
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://serpapi.com/search"
_DEFAULT_TIMEOUT = 10.0
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds


class SerpApiException(Exception):
    """SERP API 호출 실패 시 발생하는 예외"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SerpClient:
    """
    SERP API 공용 클라이언트.

    사용 예:
        client = SerpClient(api_key=settings.serp_api_key)
        data = await client.get({"engine": "google_news", "q": "삼성"})
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
    ):
        if not api_key:
            raise SerpApiException("SERP API 키가 설정되지 않았습니다.")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries

    async def get(self, params: dict) -> dict:
        """
        SERP API GET 요청. 네트워크 오류·타임아웃 시 지수 백오프로 재시도.

        Args:
            params: API 쿼리 파라미터 (api_key는 자동 삽입됨)

        Returns:
            파싱된 JSON 응답 dict

        Raises:
            SerpApiException: 최대 재시도 초과 또는 API 오류 응답
        """
        full_params = {**params, "api_key": self._api_key}
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug(
                    "[SerpClient] 요청 (시도 %d/%d) engine=%s q=%s",
                    attempt,
                    self._max_retries,
                    params.get("engine", "-"),
                    params.get("q", "-"),
                )

                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(BASE_URL, params=full_params)

                logger.debug(
                    "[SerpClient] 응답 status=%d engine=%s",
                    response.status_code,
                    params.get("engine", "-"),
                )

                if response.status_code == 429:
                    raise SerpApiException("SERP API 요청 한도 초과 (429)", status_code=429)

                if response.status_code >= 500:
                    raise SerpApiException(
                        f"SERP API 서버 오류 ({response.status_code})",
                        status_code=response.status_code,
                    )

                response.raise_for_status()
                return response.json()

            except SerpApiException:
                raise  # 재시도 불필요한 명시적 오류는 바로 전파

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                logger.warning(
                    "[SerpClient] 네트워크 오류 (시도 %d/%d): %s",
                    attempt,
                    self._max_retries,
                    str(e),
                )
                if attempt < self._max_retries:
                    wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.info("[SerpClient] %.1f초 후 재시도합니다.", wait)
                    await asyncio.sleep(wait)

            except httpx.HTTPStatusError as e:
                raise SerpApiException(
                    f"SERP API HTTP 오류: {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e

            except Exception as e:
                logger.error("[SerpClient] 예상치 못한 오류: %s", str(e), exc_info=True)
                raise SerpApiException(f"SERP API 호출 실패: {e}") from e

        raise SerpApiException(
            f"SERP API 최대 재시도({self._max_retries}회) 초과: {last_error}"
        )

    async def ping(self) -> bool:
        """
        SERP API 가용성 스모크 호출.

        Returns:
            True: 정상 응답
            False: 실패 (예외는 발생시키지 않음)
        """
        try:
            await self.get({"engine": "google", "q": "ping", "num": "1"})
            logger.info("[SerpClient] ping 성공 — SERP API 연결 확인됨.")
            return True
        except SerpApiException as e:
            logger.warning("[SerpClient] ping 실패: %s", str(e))
            return False
        except Exception as e:
            logger.warning("[SerpClient] ping 예외: %s", str(e))
            return False
