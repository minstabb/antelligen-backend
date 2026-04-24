from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TempUserInfo:
    nickname: Optional[str]
    email: Optional[str]


class TempTokenQueryPort(ABC):
    @abstractmethod
    async def find_by_token(self, token: str) -> Optional[TempUserInfo]:
        pass
