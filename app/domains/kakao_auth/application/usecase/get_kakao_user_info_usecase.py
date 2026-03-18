from app.domains.kakao_auth.application.port.out.kakao_user_info_port import KakaoUserInfoPort
from app.domains.kakao_auth.application.response.kakao_user_info_response import KakaoUserInfoResponse


class GetKakaoUserInfoUseCase:
    def __init__(self, kakao_user_info_port: KakaoUserInfoPort):
        self._port = kakao_user_info_port

    async def execute(self, access_token: str) -> KakaoUserInfoResponse:
        user_info = await self._port.fetch_user_info(access_token)
        return KakaoUserInfoResponse(
            kakao_id=user_info.kakao_id,
            nickname=user_info.nickname,
            email=user_info.email,
        )
