from abc import ABC, abstractmethod


class StudyNoteWriterPort(ABC):
    @abstractmethod
    async def append(self, markdown: str) -> str:
        pass
