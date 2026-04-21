from abc import ABC, abstractmethod

from app.domains.agent.domain.value_object.sector import Sector


class SectorLookupPort(ABC):

    @abstractmethod
    async def get_sector(self, ticker: str) -> Sector:
        pass
