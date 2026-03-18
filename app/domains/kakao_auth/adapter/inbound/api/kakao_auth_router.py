import logging

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.common.exception.app_exception import AppException
from app.common.response.base_response import BaseResponse
from app.domains.kakao_auth.adapter.outbound.external.kakao_token_client import KakaoTokenClient
from app.domains.kakao_auth.adapter.outbound.external.kakao_user_info_client import KakaoUserInfoClient
from app.domains.kakao_auth.application.usecase.generate_kakao_oauth_url_usecase import (
    GenerateKakaoOAuthUrlUseCase,
)
from app.domains.kakao_auth.application.usecase.get_kakao_user_info_usecase import GetKakaoUserInfoUseCase
from app.domains.kakao_auth.application.usecase.request_kakao_access_token_usecase import (
    RequestKakaoAccessTokenUseCase,
)
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kakao-authentication", tags=["kakao-auth"])

settings = get_settings()


@router.get("/request-oauth-link")
async def request_oauth_link():
    try:
        usecase = GenerateKakaoOAuthUrlUseCase(
            client_id=settings.kakao_client_id,
            redirect_uri=settings.kakao_redirect_uri,
        )
        url = usecase.execute()
        return RedirectResponse(url=url)
    except ValueError as e:
        raise AppException(status_code=400, message=str(e))


@router.get("/request-access-token-after-redirection")
async def request_access_token_after_redirection(
    code: str | None = None,
    error: str | None = None,
):
    if error:
        raise AppException(status_code=400, message=f"Kakao 인증 실패: {error}")
    if not code:
        raise AppException(status_code=400, message="인가 코드가 누락되었습니다.")

    try:
        token = await RequestKakaoAccessTokenUseCase(
            KakaoTokenClient(
                client_id=settings.kakao_client_id,
                redirect_uri=settings.kakao_redirect_uri,
            )
        ).execute(code)

        user_info = await GetKakaoUserInfoUseCase(
            KakaoUserInfoClient()
        ).execute(token.access_token)

        logger.info("[Kakao 사용자 정보] 닉네임: %s, 이메일: %s", user_info.nickname, user_info.email)
        print(f"[Kakao 사용자 정보] 닉네임: {user_info.nickname}, 이메일: {user_info.email}")

        return BaseResponse.ok(data=user_info, message="사용자 정보 조회 성공")
    except ValueError as e:
        raise AppException(status_code=400, message=str(e))
