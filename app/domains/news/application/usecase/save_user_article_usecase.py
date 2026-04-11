import logging

from app.common.exception.app_exception import AppException
from app.domains.news.application.port.article_content_provider import ArticleContentProvider
from app.domains.news.application.port.article_content_repository import ArticleContentRepository
from app.domains.news.application.port.user_saved_article_repository import UserSavedArticleRepository
from app.domains.news.application.request.save_user_article_request import SaveUserArticleRequest
from app.domains.news.application.response.save_user_article_response import SaveUserArticleResponse
from app.domains.news.domain.entity.user_saved_article import UserSavedArticle

logger = logging.getLogger(__name__)


class SaveUserArticleUseCase:
    def __init__(
        self,
        user_article_repo: UserSavedArticleRepository,
        content_repo: ArticleContentRepository,
        content_provider: ArticleContentProvider,
    ):
        self._user_article_repo = user_article_repo
        self._content_repo = content_repo
        self._content_provider = content_provider

    async def execute(self, account_id: int, request: SaveUserArticleRequest) -> SaveUserArticleResponse:
        # 1. 동일 사용자 + 동일 링크 중복 확인
        existing = await self._user_article_repo.find_by_user_and_link(account_id, request.link)
        if existing is not None:
            raise AppException(
                status_code=409,
                message=f"이미 저장된 기사입니다. (ID: {existing.article_id})",
            )

        # 2. 메타데이터 저장 (MySQL 역할: 구조화된 관계형 데이터)
        article = UserSavedArticle(
            account_id=account_id,
            title=request.title,
            link=request.link,
            source=request.source,
            published_at=request.published_at,
            snippet=request.snippet,
        )
        saved = await self._user_article_repo.save(article)

        # 3. 기사 본문 스크래핑 + JSONB 저장 (PostgreSQL 비정형 데이터)
        try:
            content = await self._content_provider.fetch_content(request.link)
            await self._content_repo.save(
                user_saved_article_id=saved.article_id,
                content=content,
                snippet=request.snippet,
            )
        except Exception as e:
            # JSONB 저장 실패 시 메타데이터 롤백 → 일관성 유지
            logger.error(
                "[SaveUserArticleUseCase] JSONB 저장 실패, 메타데이터 롤백. article_id=%s error=%s",
                saved.article_id,
                str(e),
            )
            try:
                await self._user_article_repo.delete_by_id(saved.article_id)
            except Exception as rollback_err:
                logger.error(
                    "[SaveUserArticleUseCase] 롤백 실패 — 수동 정리 필요. article_id=%s error=%s",
                    saved.article_id,
                    str(rollback_err),
                )
            raise AppException(
                status_code=502,
                message="기사 본문 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.",
            )

        return SaveUserArticleResponse(
            article_id=saved.article_id,
            saved_at=saved.saved_at,
        )
