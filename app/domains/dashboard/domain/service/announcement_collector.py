from typing import List

from app.domains.dashboard.domain.entity.announcement_event import AnnouncementEvent


class AnnouncementCollector:
    """두 소스(DART, SEC EDGAR)의 공시 이벤트를 병합·중복 제거하는 도메인 서비스."""

    def merge(
        self,
        primary: List[AnnouncementEvent],
        secondary: List[AnnouncementEvent],
    ) -> List[AnnouncementEvent]:
        """primary 이벤트를 우선하여 병합한다.

        중복 판정 기준: (date, type, title 앞 30자)
        """
        seen: set[tuple] = set()
        merged: List[AnnouncementEvent] = []

        for event in primary:
            key = (event.date, event.type.value, event.title[:30])
            if key not in seen:
                seen.add(key)
                merged.append(event)

        for event in secondary:
            key = (event.date, event.type.value, event.title[:30])
            if key not in seen:
                seen.add(key)
                merged.append(event)

        merged.sort(key=lambda e: e.date, reverse=True)
        return merged
