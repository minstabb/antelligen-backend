from abc import ABC, abstractmethod
from typing import List

from app.domains.schedule.domain.entity.economic_event import EconomicEvent


class EventDisambiguationPort(ABC):
    """동일 (title, event_at) 그룹의 충돌 이벤트를 외부 정보(뉴스 등)로 해소한다.

    구현 어댑터는 입력 그룹(2건 이상) 중 정답 1건을 선택해 반환한다.
    어떤 후보도 외부 정보와 일치하지 않으면 외부에서 추출한 정식 명칭으로
    title 을 덮어쓴 1건을 반환한다.
    """

    @abstractmethod
    async def resolve(
        self, conflicting_events: List[EconomicEvent]
    ) -> List[EconomicEvent]:
        ...
