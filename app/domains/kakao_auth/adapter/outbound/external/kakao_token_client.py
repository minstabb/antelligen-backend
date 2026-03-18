import httpx

from app.domains.kakao_auth.application.port.out.kakao_token_port import KakaoTokenPort
from app.domains.kakao_auth.domain.entity.kakao_token import KakaoToken

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"


class KakaoTokenClient(KakaoTokenPort):
    def __init__(self, client_id: str, redirect_uri: str):
        self._client_id = client_id
        self._redirect_uri = redirect_uri

    async def fetch_token(self, code: str) -> KakaoToken:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                KAKAO_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "client_id": self._client_id,
                    "redirect_uri": self._redirect_uri,
                    "code": code,
                },
            )

        if response.status_code != 200:
            body = response.json()
            error_desc = body.get("error_description", "Kakao 토큰 발급 실패")
            raise ValueError(error_desc)

        body = response.json()
        return KakaoToken(
            access_token=body["access_token"],
            token_type=body["token_type"],
            expires_in=body["expires_in"],
            refresh_token=body["refresh_token"],
            refresh_token_expires_in=body["refresh_token_expires_in"],
        )
