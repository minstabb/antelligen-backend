"""기업 잠정실적 일정 재수집·재저장 스케줄러 잡.

DART OpenAPI 에서 영업(잠정)실적 공시를 폴링해 과거 발표일은 실제값으로,
미래 분기는 기업별 historical 패턴 추정값으로 산출하여 DB 에 upsert 한다.
모든 발표일은 한국 영업일로 보정되어 주말/공휴일이 포함되지 않는다.

- Quarterly 잡: 분기 초(1·4·7·10월)에 새 분기 추정 일정 반영
- Weekly 잡:    매주 신규 공시 → 실제 발표일로 갱신
"""

import logging

from app.domains.schedule.adapter.outbound.external.composite_economic_event_client import (
    CompositeEconomicEventClient,
)
from app.domains.schedule.adapter.outbound.external.dart_corp_earnings_client import (
    DartCorpEarningsClient,
)
from app.domains.schedule.adapter.outbound.persistence.economic_event_repository_impl import (
    EconomicEventRepositoryImpl,
)
from app.domains.schedule.application.request.sync_economic_events_request import (
    SyncEconomicEventsRequest,
)
from app.domains.schedule.application.usecase.sync_economic_events_usecase import (
    SyncEconomicEventsUseCase,
)
from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def job_refresh_corp_earnings() -> None:
    """잠정실적 일정을 전량 재생성.

    매 실행마다 `source='corp_earnings'` 전량 삭제 후 DART 에서 다시 수집한다.
    날짜 변경·삭제·추가가 자동 반영되며, 분석 파이프라인 제외 소스이므로
    FK CASCADE 부작용 없음.
    """
    print("[corp_earnings.job] ▶ 잠정실적 일정 재수집 시작")
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        fetch_port = CompositeEconomicEventClient(
            clients=[DartCorpEarningsClient(api_key=settings.open_dart_api_key)]
        )
        repo = EconomicEventRepositoryImpl(db=session)
        usecase = SyncEconomicEventsUseCase(fetch_port=fetch_port, repository=repo)
        try:
            deleted = await repo.delete_by_source("corp_earnings")
            print(f"[corp_earnings.job] 기존 corp_earnings 이벤트 {deleted}건 삭제")

            request = SyncEconomicEventsRequest(years_back=1, years_forward=1)
            result = await usecase.execute(request)
            print(
                f"[corp_earnings.job] ✅ 완료 deleted={deleted} "
                f"fetched={result.fetched_count} new={result.new_count}"
            )
        except Exception as exc:
            print(f"[corp_earnings.job] ❌ 실패: {exc}")
            logger.exception("[corp_earnings.job] 잠정실적 재수집 실패: %s", exc)
