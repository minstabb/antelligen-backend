"""여러 EconomicEventFetchPort 를 순회하며 수집 결과를 합치는 composite 어댑터.

정책:
- 하나라도 성공하면 성공한 결과를 반환 (partial success 허용)
- 전부 실패하면 마지막 예외를 재발생
"""

import logging
from datetime import date
from typing import List, Sequence

from app.domains.schedule.application.port.out.economic_event_fetch_port import (
    EconomicEventFetchPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent

logger = logging.getLogger(__name__)


class CompositeEconomicEventClient(EconomicEventFetchPort):
    def __init__(self, clients: Sequence[EconomicEventFetchPort]):
        if not clients:
            raise ValueError("최소 1개 이상의 fetch client 가 필요합니다.")
        self._clients = list(clients)

    async def fetch(self, start: date, end: date) -> List[EconomicEvent]:
        print(f"[schedule.composite] {len(self._clients)}개 소스 수집 시작")
        all_events: List[EconomicEvent] = []
        last_error: Exception | None = None
        success_count = 0

        for client in self._clients:
            name = client.__class__.__name__
            try:
                events = await client.fetch(start, end)
                all_events.extend(events)
                success_count += 1
                print(f"[schedule.composite]   ✓ {name} -> {len(events)}건")
            except Exception as exc:
                last_error = exc
                print(f"[schedule.composite]   ⚠ {name} 실패: {exc}")
                logger.exception("[schedule.composite] %s 수집 실패: %s", name, exc)

        if success_count == 0:
            raise last_error or RuntimeError("모든 외부 데이터 소스 조회에 실패했습니다.")

        print(
            f"[schedule.composite] 수집 완료 success={success_count}/"
            f"{len(self._clients)} total_events={len(all_events)}"
        )
        return all_events
