from dataclasses import dataclass
from datetime import date
from enum import Enum


class AnnouncementEventType(str, Enum):
    MERGER_ACQUISITION = "MERGER_ACQUISITION"   # 합병 / 인수
    CONTRACT = "CONTRACT"                        # 계약 / MOU
    MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"      # CEO / 임원 교체
    ACCOUNTING_ISSUE = "ACCOUNTING_ISSUE"        # 회계 이슈 / 재무제표 정정
    REGULATORY = "REGULATORY"                    # 규제 / 소송 / 제재
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"            # 신제품 / 신기술 출시
    CRISIS = "CRISIS"                            # 리콜 / 상장폐지 / 거래정지
    MAJOR_EVENT = "MAJOR_EVENT"                  # 기타 주요사항 (fallback)


@dataclass
class AnnouncementEvent:
    date: date
    type: AnnouncementEventType
    title: str
    source: str  # "dart" | "sec_edgar"
    url: str
