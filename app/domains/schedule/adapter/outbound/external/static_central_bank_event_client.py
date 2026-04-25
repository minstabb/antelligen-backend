"""Fed / BOE / BOJ / BOK 기준금리 발표 일정 공급자.

외부 네트워크에 의존하지 않는 정적 데이터. 각 회의 발표일을 HIGH 중요도로 제공한다.
"""

import logging
from datetime import date, datetime, time, timezone
from typing import List

from app.domains.schedule.adapter.outbound.external.central_bank_meetings_data import (
    BANKS,
    MEETING_SCHEDULES,
)
from app.domains.schedule.application.port.out.economic_event_fetch_port import (
    EconomicEventFetchPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.domain.value_object.event_importance import EventImportance

logger = logging.getLogger(__name__)

SOURCE_NAME = "central_bank"


class StaticCentralBankEventClient(EconomicEventFetchPort):
    async def fetch(self, start: date, end: date) -> List[EconomicEvent]:
        print(
            f"[schedule.cb] 요청 start={start.isoformat()} end={end.isoformat()}"
        )
        events: List[EconomicEvent] = []
        for bank_key, meta in BANKS.items():
            dates = MEETING_SCHEDULES.get(bank_key, [])
            for date_iso in dates:
                try:
                    meeting_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if meeting_date < start or meeting_date > end:
                    continue
                event_at = datetime.combine(
                    meeting_date, time(0, 0), tzinfo=timezone.utc
                )
                events.append(
                    EconomicEvent(
                        source=SOURCE_NAME,
                        source_event_id=f"{bank_key}-{date_iso}",
                        title=meta.title_template,
                        country=meta.country,
                        event_at=event_at,
                        importance=EventImportance.HIGH,
                        description=(
                            f"{meta.name_ko}({meta.name_en}) 기준금리 결정 "
                            f"발표 예정"
                        ),
                        reference_url=meta.reference_url,
                    )
                )
        print(f"[schedule.cb] 범위 내 중앙은행 이벤트 = {len(events)}건")
        return events
