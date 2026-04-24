from abc import ABC, abstractmethod
from typing import Optional

from app.domains.kakao_auth.domain.entity.temp_token import TempToken


class TempTokenStorePort(ABC):
    @abstractmethod
    async def save(self, temp_token: TempToken) -> None:
        pass

    @abstractmethod
    async def find_by_token(self, token: str) -> Optional[TempToken]:
        pass
