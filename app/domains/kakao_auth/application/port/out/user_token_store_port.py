from abc import ABC, abstractmethod


class UserTokenStorePort(ABC):
    @abstractmethod
    async def save_session(self, token: str, account_id: int, ttl_seconds: int) -> None:
        pass

    @abstractmethod
    async def save_kakao_access_token(self, account_id: int, kakao_access_token: str, ttl_seconds: int) -> None:
        pass
