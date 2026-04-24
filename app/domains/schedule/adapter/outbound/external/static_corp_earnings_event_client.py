"""국내 코스피·코스닥 주요 기업 잠정실적 발표 일정 공급자.

이 이벤트들은 '경제 일정 조회/현황판 표시' 목적으로만 사용하고
매크로 영향 분석 파이프라인에서는 제외된다 (`source='corp_earnings'` 로 필터).
"""

import logging
from datetime import date, datetime, time, timezone
from typing import List

from app.domains.schedule.adapter.outbound.external.corp_earnings_calendar_data import (
    build_schedule,
)
from app.domains.schedule.application.port.out.economic_event_fetch_port import (
    EconomicEventFetchPort,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.domain.value_object.event_importance import EventImportance

logger = logging.getLogger(__name__)

SOURCE_NAME = "corp_earnings"


class StaticCorpEarningsEventClient(EconomicEventFetchPort):
    async def fetch(self, start: date, end: date) -> List[EconomicEvent]:
        years = sorted({start.year, end.year} | set(range(start.year, end.year + 1)))
        print(
            f"[schedule.corp] 요청 start={start.isoformat()} end={end.isoformat()} "
            f"years={years}"
        )

        events: List[EconomicEvent] = []
        for entry in build_schedule(years):
            try:
                event_date = datetime.strptime(entry["date_iso"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if event_date < start or event_date > end:
                continue

            event_at = datetime.combine(event_date, time(0, 0), tzinfo=timezone.utc)
            quarter_label = entry["quarter"]
            name = entry["name"]
            ticker = entry["ticker"]
            market = entry["market"]
            indices = entry.get("indices") or []
            is_early = bool(entry.get("is_early"))

            # 선공시 기업은 우선순위 표시용으로 importance=MEDIUM 부여 + 타이틀 [선공시] prefix.
            # 지수(KOSPI200/KOSDAQ150/VALUEUP) 정보는 타이틀에는 넣지 않고
            # description 에만 남겨 프론트 배지용으로 활용 가능하게 한다.
            importance = EventImportance.MEDIUM if is_early else EventImportance.LOW
            priority_prefix = "[선공시] " if is_early else ""

            desc_indices = f"소속 지수: {', '.join(indices)}. " if indices else ""
            desc_priority = "시장 대표주 선공시(우선 표시). " if is_early else ""

            events.append(
                EconomicEvent(
                    source=SOURCE_NAME,
                    source_event_id=f"{ticker}-{event_date.year}-{quarter_label}",
                    title=f"{priority_prefix}{name}({ticker}) {quarter_label} 잠정실적 발표",
                    country="KR",
                    event_at=event_at,
                    importance=importance,
                    description=(
                        f"{market} 상장사 {name}({ticker})의 {quarter_label} "
                        f"잠정실적 발표 예정. {desc_indices}{desc_priority}"
                        f"분석 파이프라인에서는 제외되며 참고용 일정 표시에만 사용됩니다."
                    ),
                    reference_url=None,
                )
            )

        print(f"[schedule.corp] 범위 내 잠정실적 이벤트 = {len(events)}건")
        return events
