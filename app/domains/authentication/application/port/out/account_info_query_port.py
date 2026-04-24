from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class AccountInfo:
    account_id: int
    email: str
    nickname: Optional[str]


class AccountInfoQueryPort(ABC):
    @abstractmethod
    async def find_by_id(self, account_id: int) -> Optional[AccountInfo]:
        pass
