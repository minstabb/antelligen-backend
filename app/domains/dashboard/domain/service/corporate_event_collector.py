from typing import List

from app.domains.dashboard.domain.entity.corporate_event import CorporateEvent


class CorporateEventCollector:
    """두 소스(yfinance, DART)의 이벤트를 병합·중복 제거하는 도메인 서비스."""

    def merge(
        self,
        dart_events: List[CorporateEvent],
        yfinance_events: List[CorporateEvent],
    ) -> List[CorporateEvent]:
        """DART 이벤트를 우선하여 병합한다.

        중복 판정 기준: (date, type) — 같은 날짜·같은 타입은 DART 우선.
        """
        seen: set[tuple] = set()
        merged: List[CorporateEvent] = []

        for event in dart_events:
            key = (event.date, event.type.value)
            if key not in seen:
                seen.add(key)
                merged.append(event)

        for event in yfinance_events:
            key = (event.date, event.type.value)
            if key not in seen:
                seen.add(key)
                merged.append(event)

        merged.sort(key=lambda e: e.date)
        return merged
