from datetime import datetime

from pydantic import BaseModel


class SaveUserArticleResponse(BaseModel):
    article_id: int
    saved_at: datetime
