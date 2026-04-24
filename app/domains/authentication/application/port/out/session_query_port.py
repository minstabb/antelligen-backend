from abc import ABC, abstractmethod
from typing import Optional


class SessionQueryPort(ABC):
    @abstractmethod
    async def get_account_id_by_session(self, token: str) -> Optional[int]:
        pass
