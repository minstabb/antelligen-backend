from abc import ABC, abstractmethod
from datetime import date
from typing import List

from app.domains.dashboard.domain.entity.announcement_event import AnnouncementEvent


class SecEdgarAnnouncementPort(ABC):
    @abstractmethod
    async def fetch_announcements(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[AnnouncementEvent]:
        """SEC EDGAR에서 8-K 공시를 수집한다.

        Raises:
            - ticker를 CIK로 변환할 수 없으면 빈 리스트 반환
        """
        pass
