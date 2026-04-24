from abc import ABC, abstractmethod


class StudyNotePort(ABC):
    @abstractmethod
    async def read(self) -> str:
        pass
