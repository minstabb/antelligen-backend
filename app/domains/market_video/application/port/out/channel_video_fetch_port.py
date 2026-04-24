from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChannelVideoItem:
    video_id: str
    title: str
    channel_name: str
    published_at: datetime
    view_count: int
    thumbnail_url: str
    video_url: str


class ChannelVideoFetchPort(ABC):
    @abstractmethod
    async def fetch_recent_videos(
        self,
        channel_ids: list[str],
        published_after: datetime,
        max_per_channel: int = 10,
    ) -> list[ChannelVideoItem]:
        pass
