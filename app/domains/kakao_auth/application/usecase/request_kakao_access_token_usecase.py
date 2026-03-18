from app.domains.kakao_auth.application.port.out.kakao_token_port import KakaoTokenPort
from app.domains.kakao_auth.application.response.kakao_token_response import KakaoTokenResponse


class RequestKakaoAccessTokenUseCase:
    def __init__(self, kakao_token_port: KakaoTokenPort):
        self._port = kakao_token_port

    async def execute(self, code: str) -> KakaoTokenResponse:
        token = await self._port.fetch_token(code)
        return KakaoTokenResponse(
            access_token=token.access_token,
            token_type=token.token_type,
            expires_in=token.expires_in,
            refresh_token=token.refresh_token,
            refresh_token_expires_in=token.refresh_token_expires_in,
        )
