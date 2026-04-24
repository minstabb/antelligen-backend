from abc import ABC, abstractmethod

from app.domains.kakao_auth.domain.entity.kakao_user_info import KakaoUserInfo


class KakaoUserInfoPort(ABC):
    @abstractmethod
    async def fetch_user_info(self, access_token: str) -> KakaoUserInfo:
        pass
