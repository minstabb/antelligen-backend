from datetime import datetime

from pydantic import BaseModel


class CreatePostResponse(BaseModel):
    post_id: int
    title: str
    content: str
    created_at: datetime
