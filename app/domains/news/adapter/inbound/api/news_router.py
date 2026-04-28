from typing import Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, Depends, Path, Cookie, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.app_exception import AppException
from app.common.response.base_response import BaseResponse
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.news.adapter.outbound.external.article_content_scraper import (
    ArticleContentScraper,
)
from app.domains.news.adapter.outbound.external.openai_article_analysis_provider import (
    OpenAIArticleAnalysisProvider,
)
from app.domains.news.adapter.outbound.external.openai_news_signal_adapter import (
    OpenAINewsSignalAdapter,
)
from app.domains.news.adapter.outbound.ticker_keyword_resolver import TickerKeywordResolver
from app.domains.stock.adapter.outbound.persistence.stock_repository_impl import StockRepositoryImpl
from app.domains.news.adapter.outbound.external.serp_news_search_provider import (
    SerpNewsSearchProvider,
)
from app.domains.account.adapter.outbound.persistence.watchlist_repository_impl import WatchlistRepositoryImpl
from app.domains.news.adapter.outbound.persistence.collected_news_repository_impl import (
    CollectedNewsRepositoryImpl,
)
from app.domains.news.adapter.outbound.persistence.saved_article_repository_impl import (
    SavedArticleRepositoryImpl,
)
from app.domains.news.application.request.save_article_request import (
    SaveArticleRequest,
)
from app.domains.news.application.request.search_news_request import SearchNewsRequest
from app.domains.news.application.response.analyze_article_response import (
    AnalyzeArticleResponse,
)
from app.domains.news.application.response.save_article_response import (
    SaveArticleResponse,
)
from app.domains.news.application.response.search_news_response import (
    SearchNewsResponse,
)
from app.domains.news.application.response.watchlist_news_feed_response import WatchlistNewsFeedResponse
from app.domains.news.application.usecase.get_watchlist_news_feed_usecase import GetWatchlistNewsFeedUseCase
from app.domains.news.application.response.saved_articles_response import (
    SavedArticlesResponse,
)
from app.domains.news.application.usecase.analyze_article_usecase import (
    AnalyzeArticleUseCase,
)
from app.domains.news.application.usecase.analyze_news_signal_usecase import (
    AnalyzeNewsSignalUseCase,
)
from app.domains.news.application.usecase.save_article_usecase import (
    SaveArticleUseCase,
)
from app.domains.news.application.usecase.search_news_usecase import SearchNewsUseCase
from app.domains.news.adapter.outbound.persistence.article_content_repository_impl import ArticleContentRepositoryImpl
from app.domains.news.adapter.outbound.persistence.user_saved_article_repository_impl import UserSavedArticleRepositoryImpl
from app.domains.news.application.request.save_user_article_request import SaveUserArticleRequest
from app.domains.news.application.response.save_user_article_response import SaveUserArticleResponse
from app.domains.news.application.usecase.save_user_article_usecase import SaveUserArticleUseCase
from app.domains.news.application.usecase.save_interest_article_usecase import SaveInterestArticleUseCase
from app.domains.news.application.usecase.get_interest_article_usecase import GetInterestArticleUseCase
from app.domains.news.application.response.save_interest_article_response import SaveInterestArticleResponse
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import get_db
from app.infrastructure.database.vector_database import get_vector_db

SESSION_KEY_PREFIX = "session:"


def _extract_token(user_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if user_token:
        return user_token
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return None

router = APIRouter(prefix="/news", tags=["News"])


@router.get("/search", response_model=BaseResponse[SearchNewsResponse])
async def search_news(
    keyword: str = Query(..., min_length=1, description="검색 키워드"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
):
    """인증 없이 뉴스를 검색하고 페이징된 결과를 반환한다."""
    settings = get_settings()
    provider = SerpNewsSearchProvider(api_key=settings.serp_api_key)
    usecase = SearchNewsUseCase(news_search_provider=provider)
    request = SearchNewsRequest(keyword=keyword, page=page, page_size=page_size)
    result = await usecase.execute(request)
    return BaseResponse.ok(data=result)


@router.get("/saved", response_model=BaseResponse[SavedArticlesResponse])
async def get_saved_articles(
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(10, ge=1, le=100, description="페이지 크기"),
    user_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """인증된 사용자의 관심 기사 목록을 최신순으로 반환한다."""
    token = _extract_token(user_token, authorization)
    if not token:
        raise AppException(status_code=401, message="인증이 필요합니다.")

    account_id_str = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if not account_id_str:
        raise AppException(status_code=401, message="세션이 만료되었거나 유효하지 않습니다.")

    account_id = int(account_id_str)
    repository = UserSavedArticleRepositoryImpl(db)
    articles, total = await repository.find_all_by_user(account_id=account_id, page=page, page_size=page_size)
    items = [
        SaveArticleResponse(
            article_id=a.article_id,
            title=a.title,
            link=a.link,
            source=a.source,
            published_at=a.published_at,
            snippet=a.snippet,
            content=None,
            saved_at=a.saved_at,
        )
        for a in articles
    ]
    return BaseResponse.ok(data=SavedArticlesResponse(
        articles=items,
        page=page,
        page_size=page_size,
        total_count=total,
    ))


@router.post("/save", response_model=BaseResponse[SaveArticleResponse], status_code=201)
async def save_article(
    request: SaveArticleRequest,
    db: AsyncSession = Depends(get_db),
):
    """인증 없이 관심 기사를 저장한다. 링크에서 본문을 스크래핑하여 함께 저장한다."""
    repository = SavedArticleRepositoryImpl(db)
    content_provider = ArticleContentScraper()
    usecase = SaveArticleUseCase(repository=repository, content_provider=content_provider)
    result = await usecase.execute(request)
    return BaseResponse.ok(data=result)


@router.get("/analyze/{article_id}", response_model=BaseResponse[AnalyzeArticleResponse])
async def analyze_article(
    article_id: int = Path(..., ge=1, description="분석할 기사 ID"),
    db: AsyncSession = Depends(get_db),
):
    """저장된 기사의 핵심 키워드와 감정 분석 결과를 반환한다."""
    settings = get_settings()
    repository = SavedArticleRepositoryImpl(db)
    analysis_provider = OpenAIArticleAnalysisProvider(api_key=settings.openai_api_key)
    usecase = AnalyzeArticleUseCase(repository=repository, analysis_provider=analysis_provider)
    result = await usecase.execute(article_id)
    return BaseResponse.ok(data=result)


@router.post("/bookmark", response_model=BaseResponse[SaveUserArticleResponse], status_code=201)
async def bookmark_article(
    request: SaveUserArticleRequest,
    user_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    vector_db: AsyncSession = Depends(get_vector_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """인증된 사용자가 관심 기사를 저장한다. 메타데이터는 PostgreSQL(구조화), 본문은 JSONB에 저장된다."""
    token = _extract_token(user_token, authorization)
    if not token:
        raise AppException(status_code=401, message="인증이 필요합니다.")

    account_id_str = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if not account_id_str:
        raise AppException(status_code=401, message="세션이 만료되었거나 유효하지 않습니다.")

    account_id = int(account_id_str)

    usecase = SaveUserArticleUseCase(
        user_article_repo=UserSavedArticleRepositoryImpl(db),
        content_repo=ArticleContentRepositoryImpl(vector_db),
        content_provider=ArticleContentScraper(),
    )
    result = await usecase.execute(account_id=account_id, request=request)
    return BaseResponse.ok(data=result)


@router.post("/interest-articles", response_model=BaseResponse[SaveInterestArticleResponse], status_code=201)
async def save_interest_article(
    request: SaveUserArticleRequest,
    user_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    vector_db: AsyncSession = Depends(get_vector_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """인증된 사용자가 관심 기사를 저장하고 원문 본문을 포함한 전체 데이터를 반환한다."""
    token = _extract_token(user_token, authorization)
    if not token:
        raise AppException(status_code=401, message="인증이 필요합니다.")

    account_id_str = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if not account_id_str:
        raise AppException(status_code=401, message="세션이 만료되었거나 유효하지 않습니다.")

    account_id = int(account_id_str)
    usecase = SaveInterestArticleUseCase(
        user_article_repo=UserSavedArticleRepositoryImpl(db),
        content_repo=ArticleContentRepositoryImpl(vector_db),
        content_provider=ArticleContentScraper(),
    )
    result = await usecase.execute(account_id=account_id, request=request)
    return BaseResponse.ok(data=result)


@router.get("/interest-articles/{article_id}", response_model=BaseResponse[SaveInterestArticleResponse])
async def get_interest_article(
    article_id: int = Path(..., ge=1, description="조회할 기사 ID"),
    user_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    vector_db: AsyncSession = Depends(get_vector_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """인증된 사용자가 저장한 관심 기사 단건을 원문 본문 포함하여 조회한다."""
    token = _extract_token(user_token, authorization)
    if not token:
        raise AppException(status_code=401, message="인증이 필요합니다.")

    account_id_str = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if not account_id_str:
        raise AppException(status_code=401, message="세션이 만료되었거나 유효하지 않습니다.")

    account_id = int(account_id_str)
    usecase = GetInterestArticleUseCase(
        user_article_repo=UserSavedArticleRepositoryImpl(db),
        content_repo=ArticleContentRepositoryImpl(vector_db),
        content_provider=ArticleContentScraper(),
    )
    result = await usecase.execute(account_id=account_id, article_id=article_id)
    return BaseResponse.ok(data=result)


@router.delete("/bookmark/{article_id}", response_model=BaseResponse[None])
async def delete_bookmark(
    article_id: int = Path(..., ge=1, description="삭제할 기사 ID"),
    user_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """인증된 사용자가 본인이 저장한 관심 기사를 삭제한다."""
    token = _extract_token(user_token, authorization)
    if not token:
        raise AppException(status_code=401, message="인증이 필요합니다.")

    account_id_str = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if not account_id_str:
        raise AppException(status_code=401, message="세션이 만료되었거나 유효하지 않습니다.")

    account_id = int(account_id_str)
    repo = UserSavedArticleRepositoryImpl(db)

    article = await repo.find_by_id(article_id)
    if article is None:
        raise AppException(status_code=404, message="저장된 기사를 찾을 수 없습니다.")
    if article.account_id != account_id:
        raise AppException(status_code=403, message="삭제 권한이 없습니다.")

    await repo.delete_by_id(article_id)
    return BaseResponse.ok(data=None)


@router.get("/agent-result", response_model=BaseResponse[SubAgentResponse])
async def get_news_agent_result(
    ticker: str = Query(..., description="종목 코드 (예: 005930)"),
    db: AsyncSession = Depends(get_vector_db),
):
    """ticker 기반으로 수집된 뉴스를 GPT로 감성 분석하여 투자 신호를 반환한다."""
    settings = get_settings()
    repository = CollectedNewsRepositoryImpl(db)
    analysis_adapter = OpenAINewsSignalAdapter(api_key=settings.openai_api_key)
    keyword_resolver = TickerKeywordResolver(StockRepositoryImpl())
    usecase = AnalyzeNewsSignalUseCase(
        repository=repository,
        analysis_port=analysis_adapter,
        keyword_resolver=keyword_resolver,
    )
    result = await usecase.execute(ticker)
    return BaseResponse.ok(data=result)


@router.get("/watchlist-feed", response_model=BaseResponse[WatchlistNewsFeedResponse])
async def get_watchlist_news_feed(
    user_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
    vector_db: AsyncSession = Depends(get_vector_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """인증된 사용자의 관심종목 기반 뉴스 피드를 반환한다."""
    token = _extract_token(user_token, authorization)
    if not token:
        raise AppException(status_code=401, message="인증이 필요합니다.")

    account_id_str = await redis.get(f"{SESSION_KEY_PREFIX}{token}")
    if not account_id_str:
        raise AppException(status_code=401, message="세션이 만료되었거나 유효하지 않습니다.")

    account_id = int(account_id_str)
    usecase = GetWatchlistNewsFeedUseCase(
        watchlist_port=WatchlistRepositoryImpl(db),
        news_repository=CollectedNewsRepositoryImpl(vector_db),
    )
    result = await usecase.execute(account_id)
    return BaseResponse.ok(data=result)