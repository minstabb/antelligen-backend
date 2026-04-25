"""§13.4 B: chart_interval 봉 단위에 맞춘 이벤트 수집 윈도우 정렬 테스트.

타임라인(chart_interval 기반) 호출 시 1D=1년 / 1W=3년 / 1M=5년 / 1Q·1Y=20년
범위로 MACRO 가 수집되는지 검증. macro-timeline(lookback 기반) 호출은
lookback_days 미전달 시 기존 _PERIOD_DAYS 매핑을 그대로 사용.

NEWS 카테고리는 2026-04-26 사용자 분류 결정으로 제거됨 — 관련 테스트도 함께 삭제.
"""

from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    _PERIOD_DAYS as _MACRO_PERIOD_DAYS,
)
from app.domains.history_agent.application.usecase.history_agent_usecase import (
    _CHART_INTERVAL_LOOKBACK_DAYS,
    _DEFAULT_CHART_INTERVAL_LOOKBACK_DAYS,
)


class TestChartIntervalLookbackMap:
    def test_chart_interval_lookback_map_aligns_to_chart_range(self):
        # ADR-0001 + §13.4 B 명세
        assert _CHART_INTERVAL_LOOKBACK_DAYS == {
            "1D": 365,
            "1W": 1_095,
            "1M": 1_825,
            "1Q": 7_300,
            "1Y": 7_300,
        }
        assert _DEFAULT_CHART_INTERVAL_LOOKBACK_DAYS == 365

    def test_macro_period_days_unchanged_for_lookback_semantics(self):
        # macro-timeline 엔드포인트가 사용하는 lookback 매핑은 보존
        assert _MACRO_PERIOD_DAYS == {
            "1W": 7, "1M": 30, "3M": 90, "6M": 180,
            "1Y": 365, "2Y": 730, "5Y": 1825, "10Y": 3650,
        }
