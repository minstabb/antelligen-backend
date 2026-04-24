from abc import ABC, abstractmethod
from typing import Optional


class TempTokenQueryPort(ABC):
    @abstractmethod
    async def find_by_token(self, token: str) -> Optional[dict]:
        pass
