from abc import ABC, abstractmethod
from typing import Optional

from app.domains.market_video.domain.entity.collected_video import CollectedVideo


class CollectedVideoRepositoryPort(ABC):
    @abstractmethod
    async def find_by_video_id(self, video_id: str) -> Optional[CollectedVideo]:
        pass

    @abstractmethod
    async def find_all(self) -> list[CollectedVideo]:
        pass

    @abstractmethod
    async def upsert(self, video: CollectedVideo) -> CollectedVideo:
        pass
