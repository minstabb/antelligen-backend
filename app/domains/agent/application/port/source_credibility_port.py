from abc import ABC, abstractmethod

from app.domains.agent.domain.value_object.sector import Sector
from app.domains.agent.domain.value_object.source_tier import SourceTier


class SourceCredibilityPort(ABC):

    @abstractmethod
    def classify(self, source_url_or_name: str, sector: Sector = Sector.UNKNOWN) -> SourceTier:
        pass
