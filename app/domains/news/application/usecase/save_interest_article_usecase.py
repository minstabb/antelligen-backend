import logging
from datetime import datetime

from app.common.exception.app_exception import AppException
from app.domains.news.application.port.article_content_provider import ArticleContentProvider
from app.domains.news.application.port.article_content_repository import ArticleContentRepository
from app.domains.news.application.port.user_saved_article_repository import UserSavedArticleRepository
from app.domains.news.application.request.save_user_article_request import SaveUserArticleRequest
from app.domains.news.application.response.save_interest_article_response import SaveInterestArticleResponse
from app.domains.news.domain.entity.user_saved_article import UserSavedArticle

logger = logging.getLogger(__name__)


class SaveInterestArticleUseCase:
    def __init__(
        self,
        user_article_repo: UserSavedArticleRepository,
        content_repo: ArticleContentRepository,
        content_provider: ArticleContentProvider,
    ):
        self._user_article_repo = user_article_repo
        self._content_repo = content_repo
        self._content_provider = content_provider

    async def execute(self, account_id: int, request: SaveUserArticleRequest) -> SaveInterestArticleResponse:
        # 1. 동일 사용자 + 동일 링크 중복 확인
        existing = await self._user_article_repo.find_by_user_and_link(account_id, request.link)
        if existing is not None:
            raise AppException(
                status_code=409,
                message=f"이미 저장된 기사입니다. (ID: {existing.article_id})",
            )

        # 2. 메타데이터 저장 (구조화 DB)
        article = UserSavedArticle(
            account_id=account_id,
            title=request.title,
            link=request.link,
            source=request.source,
            published_at=request.published_at,
            snippet=request.snippet,
        )
        saved = await self._user_article_repo.save(article)

        # 3. 본문 스크래핑 + JSONB 저장
        content = ""
        try:
            content = await self._content_provider.fetch_content(request.link)
            await self._content_repo.save(
                user_saved_article_id=saved.article_id,
                content=content,
                snippet=request.snippet,
            )
        except Exception as e:
            logger.error(
                "[SaveInterestArticleUseCase] 본문 저장 실패, 메타데이터 롤백. article_id=%s error=%s",
                saved.article_id,
                str(e),
            )
            try:
                await self._user_article_repo.delete_by_id(saved.article_id)
            except Exception as rollback_err:
                logger.error(
                    "[SaveInterestArticleUseCase] 롤백 실패 — 수동 정리 필요. article_id=%s error=%s",
                    saved.article_id,
                    str(rollback_err),
                )
            raise AppException(
                status_code=502,
                message="기사 본문 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.",
            )

        # published_at 문자열 → datetime 변환 시도
        published_at_dt: datetime | None = None
        if saved.published_at:
            try:
                published_at_dt = datetime.fromisoformat(saved.published_at)
            except ValueError:
                pass

        return SaveInterestArticleResponse(
            id=saved.article_id,
            title=saved.title,
            source=saved.source,
            link=saved.link,
            published_at=published_at_dt,
            content=content,
        )
