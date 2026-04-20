from dataclasses import dataclass
from datetime import date
from enum import Enum


class AnnouncementEventType(str, Enum):
    MERGER_ACQUISITION = "MERGER_ACQUISITION"  # 합병 / 인수
    CONTRACT = "CONTRACT"                       # 계약 / MOU
    MAJOR_EVENT = "MAJOR_EVENT"                # 기타 주요사항


@dataclass
class AnnouncementEvent:
    date: date
    type: AnnouncementEventType
    title: str
    source: str  # "dart" | "sec_edgar"
    url: str
