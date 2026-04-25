import logging
from typing import Optional

from app.domains.company_profile.application.port.out.business_overview_cache_port import (
    BusinessOverviewCachePort,
)
from app.domains.company_profile.application.port.out.business_overview_port import (
    BusinessOverviewPort,
)
from app.domains.company_profile.application.port.out.company_profile_cache_port import (
    CompanyProfileCachePort,
)
from app.domains.company_profile.application.port.out.dart_company_info_port import (
    DartCompanyInfoPort,
)
from app.domains.company_profile.application.port.out.us_company_name_port import (
    UsCompanyNamePort,
)
from app.domains.company_profile.domain.entity.company_profile import CompanyProfile
from app.domains.company_profile.domain.value_object.business_overview import BusinessOverview
from app.domains.disclosure.application.port.company_repository_port import CompanyRepositoryPort
from app.domains.disclosure.application.port.rag_chunk_repository_port import (
    RagChunkRepositoryPort,
)
from app.domains.stock.domain.service.market_region_resolver import MarketRegionResolver

logger = logging.getLogger(__name__)


PROFILE_CACHE_TTL_SECONDS = 86400      # 1d — DART 기업개황은 거의 안 변함
OVERVIEW_CACHE_TTL_SECONDS = 86400 * 7  # 7d — LLM 생성 결과
RAG_CONTEXT_CHUNK_LIMIT = 5
RAG_CONTEXT_MAX_CHARS = 3000


class GetCompanyProfileUseCase:
    def __init__(
        self,
        company_repository: CompanyRepositoryPort,
        dart_company_info: DartCompanyInfoPort,
        cache: CompanyProfileCachePort,
        rag_chunk_repository: Optional[RagChunkRepositoryPort] = None,
        business_overview: Optional[BusinessOverviewPort] = None,
        overview_cache: Optional[BusinessOverviewCachePort] = None,
        us_company_name: Optional[UsCompanyNamePort] = None,
    ):
        self._company_repo = company_repository
        self._dart = dart_company_info
        self._cache = cache
        self._rag_repo = rag_chunk_repository
        self._business_overview = business_overview
        self._overview_cache = overview_cache
        self._us_company_name = us_company_name

    async def execute(
        self, ticker: str
    ) -> tuple[Optional[CompanyProfile], Optional[BusinessOverview]]:
        """기업 정보(profile) + 사업 개요(overview)를 함께 반환한다.

        ticker 형식으로 KR/US 를 자동 판별하여 분기한다. US 는 LLM-only 경로.
        """
        region = MarketRegionResolver.resolve(ticker)
        if region.is_us():
            return await self._execute_us(ticker)

        profile = await self._fetch_profile(ticker)
        if profile is None:
            return None, None

        overview = await self._fetch_overview(profile)
        return profile, overview

    async def _execute_us(
        self, ticker: str
    ) -> tuple[Optional[CompanyProfile], Optional[BusinessOverview]]:
        """미국 종목 — DART/RAG 미적용. SEC 회사명 + LLM-only 요약."""
        upper_ticker = ticker.upper()

        company_name = upper_ticker
        if self._us_company_name is not None:
            resolved = await self._us_company_name.resolve_company_name(upper_ticker)
            if resolved:
                company_name = resolved

        profile = CompanyProfile(
            corp_code=upper_ticker,        # SEC CIK 대신 ticker 를 surrogate 로 사용
            corp_name=company_name,
            corp_name_eng=company_name,
            stock_name=company_name,
            stock_code=upper_ticker,
            ceo_nm=None,
            corp_cls="US",
            jurir_no=None,
            bizr_no=None,
            adres=None,
            hm_url=None,
            ir_url=None,
            phn_no=None,
            fax_no=None,
            induty_code=None,
            est_dt=None,
            acc_mt=None,
        )

        overview = await self._fetch_overview(profile)
        return profile, overview

    async def _fetch_profile(self, ticker: str) -> Optional[CompanyProfile]:
        cached = await self._cache.get(ticker)
        if cached is not None:
            return cached

        company = await self._company_repo.find_by_stock_code(ticker)
        if company is None:
            return None

        profile = await self._dart.fetch(company.corp_code)
        if profile is None:
            return None

        await self._cache.save(ticker, profile, PROFILE_CACHE_TTL_SECONDS)
        return profile

    async def _fetch_overview(self, profile: CompanyProfile) -> Optional[BusinessOverview]:
        if self._business_overview is None or self._overview_cache is None:
            return None

        cached = await self._overview_cache.get(profile.corp_code)
        if cached is not None:
            return cached

        rag_context = await self._gather_rag_context(profile.corp_code)

        overview = await self._business_overview.generate(
            corp_name=profile.corp_name,
            induty_code=profile.induty_code,
            rag_context=rag_context,
        )
        if overview is None:
            return None

        await self._overview_cache.save(profile.corp_code, overview, OVERVIEW_CACHE_TTL_SECONDS)
        return overview

    async def _gather_rag_context(self, corp_code: str) -> Optional[str]:
        if self._rag_repo is None:
            return None
        # DART corp_code 는 8자리 숫자. US ticker(예: AAPL) 로는 RAG 청크가 없어 즉시 None 반환.
        if not corp_code.isdigit():
            return None
        try:
            chunks = await self._rag_repo.find_business_chunks_by_corp_code(
                corp_code=corp_code,
                limit=RAG_CONTEXT_CHUNK_LIMIT,
            )
        except Exception as e:
            logger.warning("[BusinessOverview] RAG 청크 조회 실패 corp_code=%s: %s", corp_code, e)
            return None

        if not chunks:
            return None

        joined = "\n\n".join(c.chunk_text for c in chunks if c.chunk_text)
        if not joined.strip():
            return None
        return joined[:RAG_CONTEXT_MAX_CHARS]
