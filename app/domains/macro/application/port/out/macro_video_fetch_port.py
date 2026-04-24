from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

from app.domains.macro.domain.entity.macro_reference_video import MacroReferenceVideo


class MacroVideoFetchPort(ABC):
    @abstractmethod
    async def fetch_recent(
        self,
        channel_id: str,
        published_after: datetime,
    ) -> List[MacroReferenceVideo]:
        pass
