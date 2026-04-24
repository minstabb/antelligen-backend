from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TempTokenInfo:
    nickname: Optional[str]
    email: Optional[str]


class TempTokenPort(ABC):

    @abstractmethod
    async def find_by_token(self, token: str) -> Optional[TempTokenInfo]:
        pass

    @abstractmethod
    async def delete_by_token(self, token: str) -> None:
        pass
