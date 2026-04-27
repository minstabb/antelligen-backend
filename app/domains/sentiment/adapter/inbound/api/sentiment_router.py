from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response.base_response import BaseResponse
from app.domains.news.adapter.outbound.ticker_keyword_resolver import TickerKeywordResolver
from app.domains.sentiment.adapter.outbound.external.naver_finance_discussion_client import (
    NaverFinanceDiscussionClient,
)
from app.domains.sentiment.adapter.outbound.external.openai_sns_signal_adapter import (
    OpenAISnsSignalAdapter,
)
from app.domains.sentiment.adapter.outbound.external.reddit_client import RedditClient
from app.domains.sentiment.adapter.outbound.external.toss_community_client import (
    TossCommunityClient,
)
from app.domains.sentiment.adapter.outbound.persistence.sns_post_repository_impl import (
    SnsPostRepositoryImpl,
)
from app.domains.sentiment.application.usecase.analyze_sns_signal_usecase import (
    AnalyzeSnsSignalUseCase,
)
from app.domains.sentiment.application.usecase.collect_sns_posts_usecase import (
    CollectSnsPostsUseCase,
)
from app.domains.stock.adapter.outbound.persistence.stock_repository_impl import (
    StockRepositoryImpl,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.vector_database import get_vector_db

router = APIRouter(prefix="/sentiment", tags=["Sentiment"])


@router.post("/collect", status_code=201)
async def collect_sns_posts(
    ticker: str = Query(..., description="종목 티커 (예: 005930, AAPL)"),
    limit_per_platform: int = Query(50, ge=1, le=200, description="플랫폼당 수집 한도"),
    db: AsyncSession = Depends(get_vector_db),
):
    """SNS 게시물 수집 (Reddit + 네이버 종목토론 + 토스stub) → PostgreSQL 적재."""
    repository = SnsPostRepositoryImpl(db)

    # 사용 가능한 collector 조립
    reddit = RedditClient()
    collectors = []
    if reddit.is_available():
        collectors.append(reddit)
    collectors.append(NaverFinanceDiscussionClient())   # API 키 불필요, 항상 추가
    collectors.append(TossCommunityClient())            # is_available=False → gather에서 skip됨

    usecase = CollectSnsPostsUseCase(collectors=collectors, repository=repository)
    result = await usecase.execute(ticker, limit_per_platform)
    return BaseResponse.ok(data=result)


@router.post("/analyze")
async def analyze_sns_signal(
    ticker: str = Query(..., description="종목 티커 (예: 005930, AAPL)"),
    lookback_limit: int = Query(100, ge=1, le=500, description="분석할 최근 게시물 수"),
    db: AsyncSession = Depends(get_vector_db),
):
    """DB의 최근 게시물 → GPT-4o-mini 감정분석 → SnsSignalResult 반환."""
    repository = SnsPostRepositoryImpl(db)

    settings = get_settings()
    analysis_port = OpenAISnsSignalAdapter(api_key=settings.openai_api_key)

    keyword_resolver = TickerKeywordResolver(StockRepositoryImpl())

    usecase = AnalyzeSnsSignalUseCase(
        repository=repository,
        analysis_port=analysis_port,
        keyword_resolver=keyword_resolver,
    )
    result = await usecase.execute(ticker, lookback_limit)
    return BaseResponse.ok(data=result.to_dict())
