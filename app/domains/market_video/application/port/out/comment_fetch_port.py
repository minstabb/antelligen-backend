from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CommentItem:
    comment_id: str
    author_name: str
    content: str
    published_at: datetime
    like_count: int


class CommentFetchPort(ABC):
    @abstractmethod
    async def fetch_comments(
        self,
        video_id: str,
        max_count: int = 20,
        order: str = "relevance",
    ) -> list[CommentItem]:
        pass
