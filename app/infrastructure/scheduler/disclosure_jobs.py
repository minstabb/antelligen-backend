import logging
import time as _time
from datetime import datetime, timedelta

from app.infrastructure.database.database import AsyncSessionLocal
from app.infrastructure.database.vector_database import VectorAsyncSessionLocal

logger = logging.getLogger(__name__)

BOOTSTRAP_TOP_N = 10
BOOTSTRAP_DISCLOSURE_DAYS = 90

# Hardcoded top 10 companies by market cap (as of March 2026)
# Used as fallback when KRX crawling is blocked in container environments
BOOTSTRAP_TOP10_TICKERS = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("373220", "LG에너지솔루션"),
    ("207940", "삼성바이오로직스"),
    ("005380", "현대자동차"),
    ("000270", "기아"),
    ("068270", "셀트리온"),
    ("005490", "POSCO홀딩스"),
    ("035420", "NAVER"),
    ("055550", "신한지주"),
]


async def job_bootstrap():
    """System startup: load base data for top N companies by market cap.

    Skips if companies table already has data.
    """
    from app.domains.disclosure.adapter.outbound.external.dart_corp_code_client import (
        DartCorpCodeClient,
    )
    from app.domains.disclosure.adapter.outbound.external.dart_disclosure_api_client import (
        DartDisclosureApiClient,
    )
    from app.domains.disclosure.adapter.outbound.external.krx_market_cap_client import (
        KrxMarketCapClient,
    )
    from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
        CompanyRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.disclosure_repository_impl import (
        DisclosureRepositoryImpl,
    )
    from app.domains.disclosure.domain.entity.company import Company
    from app.domains.disclosure.domain.entity.disclosure import Disclosure
    from app.domains.disclosure.domain.service.disclosure_classifier import DisclosureClassifier

    total_start = _time.monotonic()
    logger.info("=" * 60)
    logger.info("[Bootstrap] Starting initial data load (top %d companies, last %d days)", BOOTSTRAP_TOP_N, BOOTSTRAP_DISCLOSURE_DAYS)
    logger.info("=" * 60)

    async with AsyncSessionLocal() as db:
        company_repo = CompanyRepositoryImpl(db)

        # -- Step 1/4: Check existing data --
        step_start = _time.monotonic()
        logger.info("[Bootstrap][1/4] Checking existing data...")
        existing = await company_repo.find_all_active()
        has_companies = len(existing) > 0
        has_top = any(c.is_top300 for c in existing) if has_companies else False

        from app.domains.disclosure.adapter.outbound.persistence.disclosure_repository_impl import (
            DisclosureRepositoryImpl as _DiscRepo,
        )
        _disc_repo = _DiscRepo(db)
        disc_count_check = await _disc_repo.find_latest_rcept_dt()
        has_disclosures = disc_count_check is not None

        if has_companies and has_top and has_disclosures:
            logger.info("[Bootstrap][1/4] Found %d companies, top300 set, disclosures exist — skipping bootstrap", len(existing))
            return
        logger.info("[Bootstrap][1/4] Status: companies=%d, top300=%s, disclosures=%s (%.1fs)",
                     len(existing), has_top, has_disclosures, _time.monotonic() - step_start)

        # -- Step 2/4: Fetch all listed companies from DART --
        if has_companies:
            logger.info("[Bootstrap][2/4] %d companies already exist — skipping DART fetch", len(existing))
            stock_to_corp = {c.stock_code: c.corp_code for c in existing if c.stock_code}
            saved_count = len(existing)
        else:
            step_start = _time.monotonic()
            logger.info("[Bootstrap][2/4] Fetching all listed companies from DART... (ZIP download -> XML parse)")
            dart_client = DartCorpCodeClient()
            corp_infos = await dart_client.fetch_all_corp_codes()
            listed_corps = [c for c in corp_infos if c.stock_code]
            logger.info("[Bootstrap][2/4] DART fetch complete: total=%d, listed=%d (%.1fs)",
                         len(corp_infos), len(listed_corps), _time.monotonic() - step_start)

            stock_to_corp = {info.stock_code: info.corp_code for info in listed_corps}

            companies = [
                Company(
                    corp_code=info.corp_code,
                    corp_name=info.corp_name,
                    stock_code=info.stock_code,
                )
                for info in listed_corps
            ]

            step_start = _time.monotonic()
            logger.info("[Bootstrap][2/4] Saving to DB... (%d companies to upsert)", len(companies))
            saved_count = await company_repo.save_bulk(companies)
            logger.info("[Bootstrap][2/4] DB save complete: %d companies (%.1fs)", saved_count, _time.monotonic() - step_start)

        # -- Step 3/4: Mark top N companies by market cap --
        if has_top:
            logger.info("[Bootstrap][3/4] Top300 flags already set — skipping")
            top_corp_codes = [c.corp_code for c in existing if c.is_top300]
            top_names = [f"{c.corp_name}({c.stock_code})" for c in existing if c.is_top300]
            updated = len(top_corp_codes)
        else:
            step_start = _time.monotonic()
            logger.info("[Bootstrap][3/4] Setting top %d companies by market cap...", BOOTSTRAP_TOP_N)

            top_corp_codes = []
            top_names = []
            try:
                krx_client = KrxMarketCapClient()
                market_cap_top = await krx_client.fetch_top_by_market_cap(BOOTSTRAP_TOP_N)
                for info in market_cap_top:
                    corp_code = stock_to_corp.get(info.stock_code)
                    if corp_code:
                        top_corp_codes.append(corp_code)
                        top_names.append(f"{info.corp_name}({info.stock_code})")
            except Exception as e:
                logger.warning("[Bootstrap][3/4] KRX fetch failed (%s) — using hardcoded list", e)

            if not top_corp_codes:
                logger.info("[Bootstrap][3/4] No KRX data — using hardcoded top 10")
                for ticker, name in BOOTSTRAP_TOP10_TICKERS:
                    corp_code = stock_to_corp.get(ticker)
                    if corp_code:
                        top_corp_codes.append(corp_code)
                        top_names.append(f"{name}({ticker})")
                    else:
                        logger.warning("[Bootstrap][3/4]   %s(%s) — corp_code not found in DB, skipping", name, ticker)

            logger.info("[Bootstrap][3/4] Top companies: %s (%.1fs)", ", ".join(top_names), _time.monotonic() - step_start)

            step_start = _time.monotonic()
            updated = await company_repo.update_top300_flags(top_corp_codes)
            logger.info("[Bootstrap][3/4] Collect target flags set: %d companies (%.1fs)", updated, _time.monotonic() - step_start)

        # -- Step 4/4: Collect disclosures for top companies --
        if has_disclosures:
            logger.info("[Bootstrap][4/4] Disclosures already exist — skipping")
            total_elapsed = _time.monotonic() - total_start
            logger.info("=" * 60)
            logger.info("[Bootstrap] Recovery complete — total %.1fs", total_elapsed)
            logger.info("=" * 60)
            return

        end_date = datetime.now().strftime("%Y%m%d")
        bgn_date = (datetime.now() - timedelta(days=BOOTSTRAP_DISCLOSURE_DAYS)).strftime("%Y%m%d")

        step_start = _time.monotonic()
        logger.info("[Bootstrap][4/4] Fetching disclosures from DART... (period: %s ~ %s, types: A/B/C/D/E parallel)", bgn_date, end_date)
        dart_api = DartDisclosureApiClient()
        disclosure_repo = DisclosureRepositoryImpl(db)

        target_types = ["A", "B", "C", "D", "E"]
        type_labels = {"A": "periodic_reports", "B": "major_events", "C": "securities", "D": "mergers_splits", "E": "equity"}

        import asyncio
        fetch_tasks = [
            dart_api.fetch_all_pages(bgn_de=bgn_date, end_de=end_date, pblntf_ty=pblntf_ty)
            for pblntf_ty in target_types
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_items = []
        for i, result in enumerate(results):
            t = target_types[i]
            if isinstance(result, Exception):
                logger.error("[Bootstrap][4/4]   Type %s (%s) — failed: %s", t, type_labels[t], result)
                continue
            all_items.extend(result)
            logger.info("[Bootstrap][4/4]   Type %s (%s) — %d items", t, type_labels[t], len(result))

        logger.info("[Bootstrap][4/4] DART fetch complete: %d total items (%.1fs)", len(all_items), _time.monotonic() - step_start)

        top_codes_set = set(top_corp_codes)
        filtered = [item for item in all_items if item.corp_code in top_codes_set]
        logger.info("[Bootstrap][4/4] Filtered to top %d companies: %d -> %d items", BOOTSTRAP_TOP_N, len(all_items), len(filtered))

        disclosures = [
            Disclosure(
                rcept_no=item.rcept_no,
                corp_code=item.corp_code,
                report_nm=item.report_nm,
                rcept_dt=datetime.strptime(item.rcept_dt, "%Y%m%d").date(),
                pblntf_ty=item.pblntf_ty,
                pblntf_detail_ty=item.pblntf_detail_ty,
                rm=item.rm,
                disclosure_group=DisclosureClassifier.classify_group(item.report_nm),
                source_mode="scheduled",
                is_core=DisclosureClassifier.is_core_disclosure(item.report_nm),
            )
            for item in filtered
        ]

        step_start = _time.monotonic()
        logger.info("[Bootstrap][4/4] Saving disclosures to DB... (%d items to upsert)", len(disclosures))
        disc_saved = await disclosure_repo.upsert_bulk(disclosures)
        logger.info("[Bootstrap][4/4] Disclosures saved: %d (duplicates skipped: %d) (%.1fs)",
                     disc_saved, len(disclosures) - disc_saved, _time.monotonic() - step_start)

        total_elapsed = _time.monotonic() - total_start
        logger.info("=" * 60)
        logger.info("[Bootstrap] Initial data load complete — total %.1fs", total_elapsed)
        logger.info("[Bootstrap]   Companies: %d saved", saved_count)
        logger.info("[Bootstrap]   Top companies: %s", ", ".join(top_names))
        logger.info("[Bootstrap]   Disclosures: %d saved (out of %d fetched, %d after filtering)", disc_saved, len(all_items), len(filtered))
        logger.info("=" * 60)


def _seasonal_date_range(months_back: int = 3) -> tuple[str, str]:
    """Calculate date range for seasonal collection. Default: last 3 months."""
    end = datetime.now()
    bgn = end - timedelta(days=months_back * 30)
    return bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d")


async def job_incremental_collect():
    """Hourly: incrementally collect disclosures since last collection."""
    from app.domains.disclosure.adapter.outbound.external.dart_disclosure_api_client import (
        DartDisclosureApiClient,
    )
    from app.domains.disclosure.adapter.outbound.persistence.collection_job_repository_impl import (
        CollectionJobRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
        CompanyRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.disclosure_repository_impl import (
        DisclosureRepositoryImpl,
    )
    from app.domains.disclosure.application.usecase.incremental_collect_usecase import (
        IncrementalCollectUseCase,
    )

    start = _time.monotonic()
    logger.info("[Scheduler][IncrementalCollect] Starting incremental disclosure collection (types: B/C/D/E)")
    try:
        async with AsyncSessionLocal() as db:
            usecase = IncrementalCollectUseCase(
                dart_disclosure_api=DartDisclosureApiClient(),
                disclosure_repository=DisclosureRepositoryImpl(db),
                company_repository=CompanyRepositoryImpl(db),
                collection_job_repository=CollectionJobRepositoryImpl(db),
            )
            result = await usecase.execute()
            elapsed = _time.monotonic() - start
            logger.info("[Scheduler][IncrementalCollect] Complete — fetched=%d, filtered=%d, saved=%d, duplicates_skipped=%d (%.1fs)",
                        result.total_fetched, result.filtered_count, result.saved_count, result.duplicate_skipped, elapsed)
    except Exception as e:
        elapsed = _time.monotonic() - start
        logger.error("[Scheduler][IncrementalCollect] Failed after %.1fs: %s", elapsed, str(e))


async def job_refresh_company_list():
    """Daily 02:00: refresh company list from DART + market cap ranking from KRX."""
    from app.domains.disclosure.adapter.outbound.external.dart_corp_code_client import (
        DartCorpCodeClient,
    )
    from app.domains.disclosure.adapter.outbound.external.krx_market_cap_client import (
        KrxMarketCapClient,
    )
    from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
        CompanyRepositoryImpl,
    )
    from app.domains.disclosure.application.usecase.refresh_company_list_usecase import (
        RefreshCompanyListUseCase,
    )

    start = _time.monotonic()
    logger.info("[Scheduler][RefreshCompanyList] Starting company list refresh (DART corp codes + KRX market cap)")
    try:
        async with AsyncSessionLocal() as db:
            usecase = RefreshCompanyListUseCase(
                company_repository=CompanyRepositoryImpl(db),
                dart_corp_code_port=DartCorpCodeClient(),
                krx_market_cap_port=KrxMarketCapClient(),
            )
            result = await usecase.execute()
            elapsed = _time.monotonic() - start
            logger.info("[Scheduler][RefreshCompanyList] Complete — fetched=%d, new_saved=%d, top300_updated=%d (%.1fs)",
                        result.total_fetched, result.new_saved, result.top300_updated, elapsed)
    except Exception as e:
        elapsed = _time.monotonic() - start
        logger.error("[Scheduler][RefreshCompanyList] Failed after %.1fs: %s", elapsed, str(e))


async def job_process_documents():
    """Daily 02:30: fetch core disclosure documents from DART, generate summaries + RAG chunks.

    Raw text (raw_text) is NOT stored in DB — processed in-memory and discarded.
    """
    from app.domains.disclosure.adapter.outbound.external.dart_document_api_client import (
        DartDocumentApiClient,
    )
    from app.domains.disclosure.adapter.outbound.external.openai_embedding_client import (
        OpenAIEmbeddingClient,
    )
    from app.domains.disclosure.adapter.outbound.persistence.disclosure_document_repository_impl import (
        DisclosureDocumentRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.disclosure_repository_impl import (
        DisclosureRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.rag_chunk_repository_impl import (
        RagChunkRepositoryImpl,
    )
    from app.domains.disclosure.application.usecase.process_disclosure_documents_usecase import (
        ProcessDisclosureDocumentsUseCase,
    )

    start = _time.monotonic()
    logger.info("[Scheduler][ProcessDocuments] Starting core disclosure document processing (summary + RAG chunks)")
    try:
        async with AsyncSessionLocal() as db:
            usecase = ProcessDisclosureDocumentsUseCase(
                dart_document_api=DartDocumentApiClient(),
                disclosure_document_repository=DisclosureDocumentRepositoryImpl(db),
                disclosure_repository=DisclosureRepositoryImpl(db),
                rag_chunk_repository=RagChunkRepositoryImpl(db),
                embedding_port=OpenAIEmbeddingClient(),
            )
            result = await usecase.execute()
            elapsed = _time.monotonic() - start
            logger.info("[Scheduler][ProcessDocuments] Complete — processed=%d, chunks_stored=%d, failed=%d (%.1fs)",
                        result["processed"], result["chunks_stored"], result["failed"], elapsed)
    except Exception as e:
        elapsed = _time.monotonic() - start
        logger.error("[Scheduler][ProcessDocuments] Failed after %.1fs: %s", elapsed, str(e))


async def job_cleanup_expired_data():
    """Daily 03:00: delete data past its retention period."""
    from app.domains.disclosure.adapter.outbound.persistence.collection_job_repository_impl import (
        CollectionJobRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.data_cleanup_repository_impl import (
        DataCleanupRepositoryImpl,
    )
    from app.domains.disclosure.application.request.cleanup_request import CleanupRequest
    from app.domains.disclosure.application.usecase.cleanup_expired_data_usecase import (
        CleanupExpiredDataUseCase,
    )

    start = _time.monotonic()
    logger.info("[Scheduler][Cleanup] Starting expired data cleanup (disclosure_retention=365d, job_retention=90d)")
    try:
        async with AsyncSessionLocal() as db:
            usecase = CleanupExpiredDataUseCase(
                data_cleanup_repository=DataCleanupRepositoryImpl(db),
                collection_job_repository=CollectionJobRepositoryImpl(db),
            )
            result = await usecase.execute(request=CleanupRequest())
            elapsed = _time.monotonic() - start
            logger.info("[Scheduler][Cleanup] Complete — deleted_disclosures=%d, deleted_jobs=%d, deleted_orphaned_chunks=%d (%.1fs)",
                        result.deleted_disclosures, result.deleted_jobs, result.deleted_orphaned_chunks, elapsed)
    except Exception as e:
        elapsed = _time.monotonic() - start
        logger.error("[Scheduler][Cleanup] Failed after %.1fs: %s", elapsed, str(e))


async def _run_seasonal_collect(pblntf_ty: str, report_name: str, months_back: int = 3):
    """Collect seasonal report disclosures for the given type."""
    from app.domains.disclosure.adapter.outbound.external.dart_disclosure_api_client import (
        DartDisclosureApiClient,
    )
    from app.domains.disclosure.adapter.outbound.persistence.collection_job_repository_impl import (
        CollectionJobRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.company_repository_impl import (
        CompanyRepositoryImpl,
    )
    from app.domains.disclosure.adapter.outbound.persistence.disclosure_repository_impl import (
        DisclosureRepositoryImpl,
    )
    from app.domains.disclosure.application.usecase.seasonal_collect_usecase import (
        SeasonalCollectUseCase,
    )

    bgn_de, end_de = _seasonal_date_range(months_back)
    start = _time.monotonic()
    logger.info("[Scheduler][SeasonalCollect] Starting %s (%s) seasonal collection (period: %s ~ %s)",
                report_name, pblntf_ty, bgn_de, end_de)
    try:
        async with AsyncSessionLocal() as db:
            usecase = SeasonalCollectUseCase(
                dart_disclosure_api=DartDisclosureApiClient(),
                disclosure_repository=DisclosureRepositoryImpl(db),
                company_repository=CompanyRepositoryImpl(db),
                collection_job_repository=CollectionJobRepositoryImpl(db),
            )
            result = await usecase.execute(
                pblntf_ty=pblntf_ty,
                bgn_de=bgn_de,
                end_de=end_de,
            )
            elapsed = _time.monotonic() - start
            logger.info("[Scheduler][SeasonalCollect] %s (%s) complete — fetched=%d, filtered=%d, saved=%d, duplicates_skipped=%d (%.1fs)",
                        report_name, pblntf_ty, result.total_fetched, result.filtered_count, result.saved_count, result.duplicate_skipped, elapsed)
    except Exception as e:
        elapsed = _time.monotonic() - start
        logger.error("[Scheduler][SeasonalCollect] %s (%s) failed after %.1fs: %s", report_name, pblntf_ty, elapsed, str(e))


async def job_collect_news():
    """Daily 06:00: collect news from Naver API and store in vector DB."""
    from app.domains.news.adapter.outbound.external.naver_news_client import NaverNewsClient
    from app.domains.news.adapter.outbound.persistence.collected_news_repository_impl import CollectedNewsRepositoryImpl
    from app.domains.news.application.usecase.collect_naver_news_usecase import CollectNaverNewsUseCase
    from app.infrastructure.config.settings import get_settings

    start = _time.monotonic()
    logger.info("[Scheduler][CollectNews] Starting Naver news collection")
    try:
        settings = get_settings()
        async with VectorAsyncSessionLocal() as db:
            repository = CollectedNewsRepositoryImpl(db)
            if await repository.has_recent_news(within_seconds=86400):
                logger.info("[Scheduler][CollectNews] Recent news found (within 24h) — skipping bootstrap")
                return
            usecase = CollectNaverNewsUseCase(
                naver_news_port=NaverNewsClient(
                    client_id=settings.naver_client_id,
                    client_secret=settings.naver_client_secret,
                ),
                repository=repository,
            )
            result = await usecase.execute()
            elapsed = _time.monotonic() - start
            logger.info("[Scheduler][CollectNews] Complete — collected=%d, skipped=%d (%.1fs)",
                        result.total_collected, result.skipped_duplicates, elapsed)
    except Exception as e:
        elapsed = _time.monotonic() - start
        logger.error("[Scheduler][CollectNews] Failed after %.1fs: %s", elapsed, str(e))


async def job_seasonal_quarterly():
    """Quarterly report (A003) seasonal collection."""
    await _run_seasonal_collect("A003", "quarterly_report")


async def job_seasonal_semiannual():
    """Semi-annual report (A002) seasonal collection."""
    await _run_seasonal_collect("A002", "semiannual_report")


async def job_seasonal_annual():
    """Annual report (A001) seasonal collection."""
    await _run_seasonal_collect("A001", "annual_report", months_back=4)
