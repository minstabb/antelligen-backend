from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from app.domains.macro.domain.value_object.risk_status import RiskStatus


@dataclass
class RiskJudgementResult:
    status: RiskStatus
    reasons: List[str] = field(default_factory=list)


class RiskJudgementLlmPort(ABC):
    @abstractmethod
    async def judge(
        self,
        reference_date: date,
        note_context: Optional[str] = None,
        video_context: Optional[str] = None,
        aligned_status: Optional[RiskStatus] = None,
    ) -> RiskJudgementResult:
        pass
