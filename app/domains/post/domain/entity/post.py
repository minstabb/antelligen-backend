from datetime import datetime
from typing import Optional


class Post:
    def __init__(
        self,
        title: str,
        content: str,
        post_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ):
        self.post_id = post_id
        self.title = title
        self.content = content
        self.created_at = created_at or datetime.now()

    @staticmethod
    def validate_title(title: str) -> bool:
        return bool(title and title.strip())

    @staticmethod
    def validate_content(content: str) -> bool:
        return bool(content and content.strip())
