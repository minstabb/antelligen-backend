from app.domains.kakao_auth.domain.value_object.kakao_oauth_url import KakaoOAuthUrl


class GenerateKakaoOAuthUrlUseCase:
    def __init__(self, client_id: str, redirect_uri: str):
        self._client_id = client_id
        self._redirect_uri = redirect_uri

    def execute(self) -> str:
        return KakaoOAuthUrl(self._client_id, self._redirect_uri).value
