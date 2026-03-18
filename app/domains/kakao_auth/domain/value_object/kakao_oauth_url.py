from urllib.parse import urlencode

KAKAO_AUTH_BASE_URL = "https://kauth.kakao.com/oauth/authorize"


class KakaoOAuthUrl:
    def __init__(self, client_id: str, redirect_uri: str):
        if not client_id:
            raise ValueError("kakao_client_id는 필수입니다.")
        if not redirect_uri:
            raise ValueError("kakao_redirect_uri는 필수입니다.")

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        }
        self._url = f"{KAKAO_AUTH_BASE_URL}?{urlencode(params)}"

    @property
    def value(self) -> str:
        return self._url
