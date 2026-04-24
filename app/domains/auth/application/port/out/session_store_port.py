from abc import ABC, abstractmethod
from typing import Optional

from app.domains.auth.domain.entity.session import Session


class SessionStorePort(ABC):
    @abstractmethod
    async def save(self, session: Session) -> None:
        pass

    @abstractmethod
    async def find_by_token(self, token: str) -> Optional[Session]:
        pass

    @abstractmethod
    async def delete(self, token: str) -> None:
        pass
