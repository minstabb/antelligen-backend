from abc import ABC, abstractmethod


class AccountTokenCachePort(ABC):

    @abstractmethod
    async def save_kakao_token(self, account_id: int, kakao_access_token: str) -> None:
        pass

    @abstractmethod
    async def issue_user_token(self, account_id: int) -> str:
        pass
