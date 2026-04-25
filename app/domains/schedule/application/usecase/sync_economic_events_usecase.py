import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List

from app.common.exception.app_exception import AppException
from app.domains.schedule.application.port.out.economic_event_fetch_port import (
    EconomicEventFetchPort,
)
from app.domains.schedule.application.port.out.economic_event_repository_port import (
    EconomicEventRepositoryPort,
)
from app.domains.schedule.application.request.sync_economic_events_request import (
    SyncEconomicEventsRequest,
)
from app.domains.schedule.application.response.economic_event_response import (
    SyncEconomicEventsResponse,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent

logger = logging.getLogger(__name__)


class SyncEconomicEventsUseCase:
    def __init__(
        self,
        fetch_port: EconomicEventFetchPort,
        repository: EconomicEventRepositoryPort,
    ):
        self._fetch_port = fetch_port
        self._repository = repository

    async def execute(self, request: SyncEconomicEventsRequest) -> SyncEconomicEventsResponse:
        base_year = request.year or date.today().year
        start_year = base_year - request.years_back
        end_year = base_year + request.years_forward
        start = date(start_year, 1, 1)
        end = date(end_year, 12, 31)

        print(
            f"[schedule.sync] ▶ 동기화 시작 base_year={base_year} "
            f"range={start.isoformat()}~{end.isoformat()}"
        )

        try:
            events = await self._fetch_port.fetch(start, end)
        except Exception as exc:
            print(f"[schedule.sync]   ❌ 외부 조회 실패: {exc}")
            logger.exception("[schedule.sync] 외부 경제 일정 조회 실패: %s", exc)
            raise AppException(
                status_code=502,
                message=f"외부 데이터 소스에서 경제 일정 조회에 실패했습니다: {exc}",
            ) from exc

        if not events:
            print("[schedule.sync] 조회된 이벤트 없음 — 저장 스킵")
            return SyncEconomicEventsResponse(
                fetched_count=0,
                new_count=0,
                duplicate_count=0,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )

        # 입력 내 중복 제거 (같은 배치에 동일 (source, source_event_id) 가 있을 수 있음)
        deduped: List[EconomicEvent] = []
        seen_pairs: set[tuple[str, str]] = set()
        for e in events:
            key = (e.source, e.source_event_id)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            deduped.append(e)

        # source 별로 기존 DB 상 존재 여부 확인
        by_source: Dict[str, List[str]] = defaultdict(list)
        for e in deduped:
            by_source[e.source].append(e.source_event_id)

        existing_pairs: set[tuple[str, str]] = set()
        for source, ids in by_source.items():
            existing = await self._repository.existing_source_ids(source, ids)
            for sid in existing:
                existing_pairs.add((source, sid))

        new_events = [
            e for e in deduped if (e.source, e.source_event_id) not in existing_pairs
        ]

        print(
            f"[schedule.sync] fetched={len(events)} deduped_input={len(deduped)} "
            f"existing={len(existing_pairs)} new={len(new_events)} "
            f"sources={sorted(by_source.keys())}"
        )

        saved = await self._repository.save_all(new_events)

        print(
            f"[schedule.sync] ■ 완료 saved={saved} duplicated={len(deduped) - len(new_events)}"
        )

        return SyncEconomicEventsResponse(
            fetched_count=len(events),
            new_count=saved,
            duplicate_count=len(deduped) - len(new_events),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
