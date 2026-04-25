from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional

from app.domains.history_agent.domain.entity.curated_macro_event import CuratedMacroEvent


class CuratedMacroEventsPort(ABC):

    @abstractmethod
    async def fetch(
        self,
        *,
        region: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[CuratedMacroEvent]:
        """region(US/KR/GLOBAL) 및 선택적 기간 필터에 맞는 큐레이션된 매크로 이벤트를 반환한다.

        `start_date`/`end_date`가 None이면 해당 방향 필터를 적용하지 않는다.
        MACRO 타임라인은 period와 무관하게 과거 중요 이벤트(리먼/COVID 등)를 노출해야 하므로
        호출부는 기본적으로 둘 다 None으로 호출하고 LLM 랭커에 정렬을 위임한다.
        """
        ...
