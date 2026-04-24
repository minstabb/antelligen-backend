"""분기 초 잠정실적 일정 재수집·재저장 스케줄러 잡.

KRX 에 각 기업이 실제 공시 일정을 통보하는 시점이 분기 종료 후 1~2주 즈음이므로,
1월 초 / 4월 초 / 7월 초 / 10월 초에 재수집하여 신규 일정을 upsert 한다.

현재 구현은 `StaticCorpEarningsEventClient` 정적 데이터를 재생성해 DB 에 upsert 하는 구조.
추후 KRX KIND / DART 공시 스크래퍼로 교체 시 이 잡 내부의 fetch client 만 교체하면 된다.
"""

import logging

from app.domains.schedule.adapter.outbound.external.composite_economic_event_client import (
    CompositeEconomicEventClient,
)
from app.domains.schedule.adapter.outbound.external.static_corp_earnings_event_client import (
    StaticCorpEarningsEventClient,
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
from app.infrastructure.database.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def job_refresh_corp_earnings() -> None:
    """잠정실적 일정을 전량 재생성.

    정적 데이터 파일(`corp_earnings_calendar_data.py`)이 진실의 원천이므로,
    매 실행마다 `source='corp_earnings'` 전량 삭제 후 현재 데이터로 재삽입한다.
    날짜 변경·삭제·추가가 자동 반영되며, 분석 파이프라인 제외 소스이므로 FK CASCADE 부작용 없음.
    """
    print("[corp_earnings.job] ▶ 잠정실적 일정 재수집 시작")
    async with AsyncSessionLocal() as session:
        fetch_port = CompositeEconomicEventClient(
            clients=[StaticCorpEarningsEventClient()]
        )
        repo = EconomicEventRepositoryImpl(db=session)
        usecase = SyncEconomicEventsUseCase(fetch_port=fetch_port, repository=repo)
        try:
            deleted = await repo.delete_by_source("corp_earnings")
            print(f"[corp_earnings.job] 기존 corp_earnings 이벤트 {deleted}건 삭제")

            # 전·올해·내년 3개년 범위로 수집 (신규 연도 자동 반영)
            request = SyncEconomicEventsRequest(years_back=1, years_forward=1)
            result = await usecase.execute(request)
            print(
                f"[corp_earnings.job] ✅ 완료 deleted={deleted} "
                f"fetched={result.fetched_count} new={result.new_count}"
            )
        except Exception as exc:
            print(f"[corp_earnings.job] ❌ 실패: {exc}")
            logger.exception("[corp_earnings.job] 잠정실적 재수집 실패: %s", exc)
