from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from app.domains.market_video.domain.entity.video_item import VideoItem


@dataclass
class YoutubeVideoSearchResult:
    items: List[VideoItem]
    next_page_token: Optional[str]
    prev_page_token: Optional[str]
    total_results: int


class YoutubeVideoProvider(ABC):
    @abstractmethod
    async def search(self, page_token: Optional[str] = None) -> YoutubeVideoSearchResult:
        pass
