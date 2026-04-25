"""§13.4 B: chart_interval 봉 단위에 맞춘 이벤트 수집 윈도우 정렬 테스트.

타임라인(chart_interval 기반) 호출 시 1D=1년 / 1W=3년 / 1M=5년 / 1Q·1Y=20년
범위로 NEWS·MACRO 가 수집되는지 검증. macro-timeline(lookback 기반)
호출은 lookback_days 미전달 시 기존 _PERIOD_DAYS 매핑을 그대로 사용.
"""

from datetime import date, timedelta
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.history_agent.adapter.outbound.composite_news_provider import (
    CompositeNewsProvider,
    _DEFAULT_PERIOD_DAYS,
    _PERIOD_DAYS as _NEWS_PERIOD_DAYS,
)
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
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

    def test_news_period_days_unchanged(self):
        # composite_news_provider 의 lookback 매핑도 보존 (macro-timeline 경로 호환)
        assert _NEWS_PERIOD_DAYS["1Y"] == 365
        assert _NEWS_PERIOD_DAYS["5Y"] == 1825


class TestCompositeNewsProviderLookbackOverride:
    @pytest.mark.asyncio
    async def test_lookback_days_overrides_period_lookup(self):
        # _PERIOD_DAYS["1W"] = 7 이지만 lookback_days=1095 명시 시 1095 우선
        provider = CompositeNewsProvider(
            finnhub=MagicMock(), gdelt=MagicMock(),
            yahoo=MagicMock(), naver=MagicMock(),
        )
        # 모든 source 를 빈 결과로 mock — start_date 만 검증
        captured_start: List[date] = []

        async def _empty(start, end, **kwargs):
            captured_start.append(start)
            return []

        provider._us_sources = lambda ticker, start, end: [
            ("mock", lambda: _empty(start, end))
        ]

        await provider.fetch_news(
            ticker="AAPL", period="1W", region="US", top_n=10,
            lookback_days=1_095,
        )
        assert captured_start
        expected = date.today() - timedelta(days=1_095)
        assert captured_start[0] == expected

    @pytest.mark.asyncio
    async def test_no_lookback_days_falls_back_to_period_dict(self):
        provider = CompositeNewsProvider(
            finnhub=MagicMock(), gdelt=MagicMock(),
            yahoo=MagicMock(), naver=MagicMock(),
        )
        captured_start: List[date] = []

        async def _empty(start, end, **kwargs):
            captured_start.append(start)
            return []

        provider._us_sources = lambda ticker, start, end: [
            ("mock", lambda: _empty(start, end))
        ]

        await provider.fetch_news(
            ticker="AAPL", period="1W", region="US", top_n=10,
        )
        assert captured_start
        # _PERIOD_DAYS["1W"] = 7
        expected = date.today() - timedelta(days=7)
        assert captured_start[0] == expected

    @pytest.mark.asyncio
    async def test_unknown_period_uses_default(self):
        provider = CompositeNewsProvider(
            finnhub=MagicMock(), gdelt=MagicMock(),
            yahoo=MagicMock(), naver=MagicMock(),
        )
        captured_start: List[date] = []

        async def _empty(start, end, **kwargs):
            captured_start.append(start)
            return []

        provider._us_sources = lambda ticker, start, end: [
            ("mock", lambda: _empty(start, end))
        ]

        await provider.fetch_news(
            ticker="AAPL", period="UNKNOWN", region="US", top_n=10,
        )
        expected = date.today() - timedelta(days=_DEFAULT_PERIOD_DAYS)
        assert captured_start[0] == expected
