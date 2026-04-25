"""DART 보고서명 → AnnouncementEventType 세분류 매핑 검증.

2026-04-26 사용자 분류 결정으로 임원변동 / 회계 이슈 / 소송 / 리콜 / 상폐 등 시점 명확 사건을
ANNOUNCEMENT 카테고리에서 별도 라벨링. 이전엔 모두 MAJOR_EVENT.
"""

from app.domains.dashboard.adapter.outbound.external.dart_announcement_client import _classify
from app.domains.dashboard.domain.entity.announcement_event import AnnouncementEventType


class TestDartClassification:
    def test_관리이사_변경_is_management_change(self):
        assert _classify("대표이사 변경 공시") == AnnouncementEventType.MANAGEMENT_CHANGE

    def test_임원변동_is_management_change(self):
        assert _classify("임원변동 보고") == AnnouncementEventType.MANAGEMENT_CHANGE

    def test_임원_주요주주_is_management_change(self):
        assert _classify("임원ㆍ주요주주 특정증권등 소유상황보고서") == AnnouncementEventType.MANAGEMENT_CHANGE

    def test_회계감사_부적정_is_accounting_issue(self):
        assert _classify("회계감사 부적정 의견") == AnnouncementEventType.ACCOUNTING_ISSUE

    def test_재무제표_정정_is_accounting_issue(self):
        assert _classify("재무제표 정정공시") == AnnouncementEventType.ACCOUNTING_ISSUE

    def test_소송_is_regulatory(self):
        assert _classify("주요소송 등의 제기") == AnnouncementEventType.REGULATORY

    def test_과징금_is_regulatory(self):
        assert _classify("공정거래위원회 과징금 부과") == AnnouncementEventType.REGULATORY

    def test_상장폐지_is_crisis(self):
        assert _classify("상장폐지 사유 발생") == AnnouncementEventType.CRISIS

    def test_거래정지_is_crisis(self):
        assert _classify("주권매매거래정지") == AnnouncementEventType.CRISIS

    def test_리콜_is_crisis(self):
        assert _classify("제품 리콜 결정") == AnnouncementEventType.CRISIS

    def test_합병_is_merger_acquisition(self):
        assert _classify("회사합병 결정") == AnnouncementEventType.MERGER_ACQUISITION

    def test_주식교환_is_merger_acquisition(self):
        assert _classify("주식교환계약 체결") == AnnouncementEventType.MERGER_ACQUISITION

    def test_업무협약_is_contract(self):
        assert _classify("업무협약 체결") == AnnouncementEventType.CONTRACT

    def test_unknown_falls_back_to_major_event(self):
        assert _classify("기타 일반 공시") == AnnouncementEventType.MAJOR_EVENT

    def test_priority_crisis_before_management(self):
        # "상장폐지" 가 "임원" 보다 우선 — 거래정지 사건이 본질
        assert _classify("상장폐지로 인한 임원 변경") == AnnouncementEventType.CRISIS
