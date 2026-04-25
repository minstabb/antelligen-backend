"""SEC 8-K Item / 본문 키워드 → AnnouncementEventType 세분류 매핑 검증.

2026-04-26 사용자 분류 결정으로 5.02/4.02/3.01 등 시점 명확 사건을 별도 라벨링.
이전: 5.02 → MAJOR_EVENT 한 통.
신규: 5.02 → MANAGEMENT_CHANGE, 4.02 → ACCOUNTING_ISSUE, 3.01 → CRISIS.
"""

from app.domains.dashboard.adapter.outbound.external.sec_edgar_announcement_client import (
    _classify_by_items,
    _classify_by_title,
)
from app.domains.dashboard.domain.entity.announcement_event import AnnouncementEventType


class TestItemCodeClassification:
    def test_item_2_01_is_merger_acquisition(self):
        assert _classify_by_items("2.01") == AnnouncementEventType.MERGER_ACQUISITION

    def test_item_1_01_is_contract(self):
        assert _classify_by_items("1.01") == AnnouncementEventType.CONTRACT

    def test_item_5_02_is_management_change(self):
        assert _classify_by_items("5.02") == AnnouncementEventType.MANAGEMENT_CHANGE

    def test_item_4_02_is_accounting_issue(self):
        assert _classify_by_items("4.02") == AnnouncementEventType.ACCOUNTING_ISSUE

    def test_item_3_01_is_crisis(self):
        assert _classify_by_items("3.01") == AnnouncementEventType.CRISIS

    def test_item_8_01_is_major_event_fallback(self):
        assert _classify_by_items("8.01") == AnnouncementEventType.MAJOR_EVENT

    def test_unknown_item_falls_back_to_major_event(self):
        assert _classify_by_items("9.99") == AnnouncementEventType.MAJOR_EVENT

    def test_compound_items_picks_first_match(self):
        # "2.01, 9.01" → MERGER_ACQUISITION (2.01 우선)
        assert _classify_by_items("2.01, 9.01") == AnnouncementEventType.MERGER_ACQUISITION


class TestTitleKeywordClassification:
    def test_recall_keyword_is_crisis(self):
        assert _classify_by_title("Tesla announces vehicle recall") == AnnouncementEventType.CRISIS

    def test_lawsuit_keyword_is_regulatory(self):
        assert _classify_by_title("Lawsuit filed against company") == AnnouncementEventType.REGULATORY

    def test_settlement_keyword_is_regulatory(self):
        assert _classify_by_title("Reaches settlement with SEC") == AnnouncementEventType.REGULATORY

    def test_ceo_keyword_is_management_change(self):
        assert _classify_by_title("New CEO appointed") == AnnouncementEventType.MANAGEMENT_CHANGE

    def test_resignation_keyword_is_management_change(self):
        assert _classify_by_title("CFO Resignation announced") == AnnouncementEventType.MANAGEMENT_CHANGE

    def test_launch_keyword_is_product_launch(self):
        assert _classify_by_title("Company unveils new product launch") == AnnouncementEventType.PRODUCT_LAUNCH

    def test_restatement_keyword_is_accounting_issue(self):
        assert _classify_by_title("Restatement of financial results") == AnnouncementEventType.ACCOUNTING_ISSUE

    def test_unrelated_title_returns_none(self):
        assert _classify_by_title("Quarterly update") is None

    def test_merger_keyword_still_works(self):
        assert _classify_by_title("Definitive Agreement to merger") == AnnouncementEventType.MERGER_ACQUISITION

    def test_keyword_priority_first_match_wins(self):
        # "merger" 가 "agreement" 보다 먼저 나오므로 MERGER_ACQUISITION 우선
        assert _classify_by_title("merger agreement") == AnnouncementEventType.MERGER_ACQUISITION
