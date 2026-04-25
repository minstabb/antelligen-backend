"""History Agent 의존성 주입 모듈.

라우터는 FastAPI `Depends`로 여기의 팩토리를 호출한다. 외부 클라이언트는
stateless이므로 모듈 스코프 singleton으로 유지해 재생성 비용을 없앤다.
"""

from functools import lru_cache

import redis.asyncio as aioredis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.dashboard.adapter.outbound.external.cached_asset_type_adapter import (
    CachedAssetTypeAdapter,
)
from app.domains.dashboard.adapter.outbound.external.dart_announcement_client import (
    DartAnnouncementClient,
)
from app.domains.dashboard.adapter.outbound.external.dart_corporate_event_client import (
    DartCorporateEventClient,
)
from app.domains.dashboard.adapter.outbound.external.fred_macro_client import FredMacroClient
from app.domains.dashboard.adapter.outbound.external.sec_edgar_announcement_client import (
    SecEdgarAnnouncementClient,
)
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_asset_type_client import (
    YahooFinanceAssetTypeClient,
)
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_corporate_event_client import (
    YahooFinanceCorporateEventClient,
)
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_etf_holdings_client import (
    YahooFinanceEtfHoldingsClient,
)
from app.domains.dashboard.adapter.outbound.external.yahoo_finance_stock_client import (
    YahooFinanceStockClient,
)
from app.domains.history_agent.adapter.outbound.composite_news_provider import (
    CompositeNewsProvider,
)
from app.domains.history_agent.adapter.outbound.curated_macro_events_adapter import (
    CuratedMacroEventsAdapter,
)
from app.domains.history_agent.adapter.outbound.finnhub_fundamentals_adapter import (
    FinnhubFundamentalsAdapter,
)
from app.domains.history_agent.adapter.outbound.macro_context_adapter import (
    GprIndexAdapter,
    RelatedAssetsAdapter,
)
from app.domains.history_agent.adapter.outbound.persistence.event_enrichment_repository_impl import (
    EventEnrichmentRepositoryImpl,
)
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
)
from app.domains.history_agent.application.usecase.generate_titles_usecase import (
    GenerateTitlesUseCase,
)
from app.domains.history_agent.application.usecase.get_anomaly_causality_usecase import (
    GetAnomalyCausalityUseCase,
)
from app.domains.history_agent.application.usecase.history_agent_usecase import HistoryAgentUseCase
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.database.database import get_db


@lru_cache(maxsize=1)
def _stock_bars_port() -> YahooFinanceStockClient:
    return YahooFinanceStockClient()


@lru_cache(maxsize=1)
def _yfinance_corporate_port() -> YahooFinanceCorporateEventClient:
    return YahooFinanceCorporateEventClient()


@lru_cache(maxsize=1)
def _dart_corporate_client() -> DartCorporateEventClient:
    return DartCorporateEventClient()


@lru_cache(maxsize=1)
def _sec_edgar_port() -> SecEdgarAnnouncementClient:
    return SecEdgarAnnouncementClient()


@lru_cache(maxsize=1)
def _dart_announcement_client() -> DartAnnouncementClient:
    return DartAnnouncementClient()


@lru_cache(maxsize=1)
def _asset_type_port() -> YahooFinanceAssetTypeClient:
    return YahooFinanceAssetTypeClient()


@lru_cache(maxsize=1)
def _fred_macro_port() -> FredMacroClient:
    return FredMacroClient()


@lru_cache(maxsize=1)
def _etf_holdings_port() -> YahooFinanceEtfHoldingsClient:
    return YahooFinanceEtfHoldingsClient()


@lru_cache(maxsize=1)
def _news_port() -> CompositeNewsProvider:
    return CompositeNewsProvider()


@lru_cache(maxsize=1)
def _fundamentals_port() -> FinnhubFundamentalsAdapter:
    return FinnhubFundamentalsAdapter()


@lru_cache(maxsize=1)
def _related_assets_port() -> RelatedAssetsAdapter:
    return RelatedAssetsAdapter()


@lru_cache(maxsize=1)
def _gpr_index_port() -> GprIndexAdapter:
    return GprIndexAdapter()


@lru_cache(maxsize=1)
def _curated_macro_events_port() -> CuratedMacroEventsAdapter:
    return CuratedMacroEventsAdapter()


def get_history_agent_usecase(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> HistoryAgentUseCase:
    # A-3: asset_type 은 Redis+프로세스 로컬로 장기 캐시(24h) 감싸서 재호출 비용 제거.
    cached_asset_type_port = CachedAssetTypeAdapter(_asset_type_port(), redis)
    enrichment_repo = EventEnrichmentRepositoryImpl(db)
    collect_macro_uc = CollectImportantMacroEventsUseCase(
        fred_macro_port=_fred_macro_port(),
        curated_port=_curated_macro_events_port(),
        related_assets_port=_related_assets_port(),
        gpr_index_port=_gpr_index_port(),
        enrichment_repo=enrichment_repo,
    )
    return HistoryAgentUseCase(
        stock_bars_port=_stock_bars_port(),
        yfinance_corporate_port=_yfinance_corporate_port(),
        dart_corporate_client=_dart_corporate_client(),
        sec_edgar_port=_sec_edgar_port(),
        dart_announcement_client=_dart_announcement_client(),
        redis=redis,
        enrichment_repo=enrichment_repo,
        asset_type_port=cached_asset_type_port,
        fred_macro_port=_fred_macro_port(),
        collect_macro_events_uc=collect_macro_uc,
        etf_holdings_port=_etf_holdings_port(),
        news_port=_news_port(),
        fundamentals_port=_fundamentals_port(),
        related_assets_port=_related_assets_port(),
        gpr_index_port=_gpr_index_port(),
    )


def get_collect_important_macro_events_usecase(
    db: AsyncSession = Depends(get_db),
) -> CollectImportantMacroEventsUseCase:
    return CollectImportantMacroEventsUseCase(
        fred_macro_port=_fred_macro_port(),
        curated_port=_curated_macro_events_port(),
        related_assets_port=_related_assets_port(),
        gpr_index_port=_gpr_index_port(),
        enrichment_repo=EventEnrichmentRepositoryImpl(db),
    )


def get_generate_titles_usecase(
    db: AsyncSession = Depends(get_db),
) -> GenerateTitlesUseCase:
    return GenerateTitlesUseCase(
        enrichment_repo=EventEnrichmentRepositoryImpl(db),
    )


def get_anomaly_causality_usecase(
    db: AsyncSession = Depends(get_db),
) -> GetAnomalyCausalityUseCase:
    return GetAnomalyCausalityUseCase(
        enrichment_repo=EventEnrichmentRepositoryImpl(db),
    )


def get_fred_macro_port() -> FredMacroClient:
    """관리용 엔드포인트에서 FRED 헬스 체크 시 사용."""
    return _fred_macro_port()
