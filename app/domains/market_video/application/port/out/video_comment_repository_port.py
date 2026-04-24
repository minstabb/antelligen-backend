from abc import ABC, abstractmethod

from app.domains.market_video.domain.entity.video_comment import VideoComment


class VideoCommentRepositoryPort(ABC):
    @abstractmethod
    async def save_all(self, comments: list[VideoComment]) -> None:
        pass

    @abstractmethod
    async def find_all(self) -> list[VideoComment]:
        pass
