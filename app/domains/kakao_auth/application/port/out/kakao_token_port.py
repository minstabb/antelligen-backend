from abc import ABC, abstractmethod

from app.domains.kakao_auth.domain.entity.kakao_token import KakaoToken


class KakaoTokenPort(ABC):
    @abstractmethod
    async def fetch_token(self, code: str) -> KakaoToken:
        pass
