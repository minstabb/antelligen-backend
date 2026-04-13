from datetime import datetime

from app.common.exception.app_exception import AppException
from app.domains.news.application.port.article_content_repository import ArticleContentRepository
from app.domains.news.application.port.user_saved_article_repository import UserSavedArticleRepository
from app.domains.news.application.response.save_interest_article_response import SaveInterestArticleResponse


class GetInterestArticleUseCase:
    def __init__(
        self,
        user_article_repo: UserSavedArticleRepository,
        content_repo: ArticleContentRepository,
    ):
        self._user_article_repo = user_article_repo
        self._content_repo = content_repo

    async def execute(self, account_id: int, article_id: int) -> SaveInterestArticleResponse:
        article = await self._user_article_repo.find_by_id(article_id)
        if article is None:
            raise AppException(status_code=404, message="저장된 기사를 찾을 수 없습니다.")
        if article.account_id != account_id:
            raise AppException(status_code=403, message="조회 권한이 없습니다.")

        content = await self._content_repo.find_by_article_id(article_id) or ""

        published_at_dt: datetime | None = None
        if article.published_at:
            try:
                published_at_dt = datetime.fromisoformat(article.published_at)
            except ValueError:
                pass

        return SaveInterestArticleResponse(
            id=article.article_id,
            title=article.title,
            source=article.source,
            link=article.link,
            published_at=published_at_dt,
            content=content,
        )
