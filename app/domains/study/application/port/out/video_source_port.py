from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from app.domains.study.domain.entity.study_video_input import StudyVideoInput


class VideoSourcePort(ABC):
    @abstractmethod
    async def fetch_by_channels(
        self,
        channel_ids: List[str],
        published_after: Optional[datetime] = None,
        max_per_channel: int = 20,
    ) -> List[StudyVideoInput]:
        pass
