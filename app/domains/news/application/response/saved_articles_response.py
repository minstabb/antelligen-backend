from pydantic import BaseModel

from app.domains.news.application.response.save_article_response import SaveArticleResponse


class SavedArticlesResponse(BaseModel):
    articles: list[SaveArticleResponse]
    page: int
    page_size: int
    total_count: int
