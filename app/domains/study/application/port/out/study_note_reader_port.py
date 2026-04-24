from abc import ABC, abstractmethod
from typing import Set


class StudyNoteReaderPort(ABC):
    @abstractmethod
    async def existing_video_ids(self) -> Set[str]:
        pass
