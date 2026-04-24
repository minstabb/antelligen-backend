from abc import ABC, abstractmethod
from typing import Optional


class TranscriptFetchPort(ABC):
    @abstractmethod
    async def fetch(self, video_id: str) -> Optional[str]:
        pass
