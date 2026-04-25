import logging

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.company_profile.adapter.outbound.cache.business_overview_cache import (
    RedisBusinessOverviewCache,
)
from app.domains.company_profile.adapter.outbound.cache.company_profile_cache import (
    RedisCompanyProfileCache,
)
from app.domains.company_profile.adapter.outbound.external.dart_company_info_client import (
    DartCompanyInfoClient,
)
from app.domains.company_profile.adapter.outbound.external.openai_business_overview_client import (
    OpenAIBusinessOverviewClient,
)
from app.domains.company_profile.adapter.outbound.external.sec_company_name_adapter import (
    SecCompanyNameAdapter,
)
from app.domains.company_profile.application.response.company_profile_response import (
    CompanyProfileResponse,
)
from app.domains.company_profile.application.usecase.get_company_profile_usecase import (
    GetCompanyProfileUseCase,
)
from app.domains.disclosure.adapter.outbound.external.sec_edgar_api_client import (
    SecEdgarApiClient,
)
from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
    CompanyRepositoryImpl,
)
from app.domains.disclosure.adapter.outbound.persistence.rag_chunk_repository_impl import (
    RagChunkRepositoryImpl,
)
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/company-profile", tags=["company-profile"])


@router.get("/{ticker}", response_model=CompanyProfileResponse)
async def get_company_profile(
    ticker: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    settings = get_settings()
    sec_client = SecEdgarApiClient(user_agent=settings.sec_edgar_user_agent)

    usecase = GetCompanyProfileUseCase(
        company_repository=CompanyRepositoryImpl(db),
        dart_company_info=DartCompanyInfoClient(),
        cache=RedisCompanyProfileCache(redis),
        rag_chunk_repository=RagChunkRepositoryImpl(db),
        business_overview=OpenAIBusinessOverviewClient(),
        overview_cache=RedisBusinessOverviewCache(redis),
        us_company_name=SecCompanyNameAdapter(sec_client),
    )
    profile, overview = await usecase.execute(ticker)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"Company profile not found for ticker '{ticker}'.",
        )
    return CompanyProfileResponse.from_entity(profile, overview)
