"""CompositeNewsProvider — fail-over chain + dedup 동작 검증."""

import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.history_agent.adapter.outbound.composite_news_provider import (
    CompositeNewsProvider,
    _dedup,
    _jaccard_similarity,
    _period_to_start,
)
from app.domains.history_agent.application.port.out.news_event_port import NewsItem


def _stub_client(articles: List[Dict[str, Any]]) -> Any:
    client = MagicMock()
    client.fetch_articles = AsyncMock(return_value=articles)
    return client


@pytest.mark.asyncio
async def test_failover_uses_primary_when_it_returns_items():
    finnhub = _stub_client(
        [
            {
                "date": "20260101",
                "title": "Apple beats estimates",
                "url": "https://f.example/apple",
                "tone": 0.5,
            }
        ]
    )
    gdelt = _stub_client([])
    yahoo = _stub_client([])
    naver = MagicMock()

    provider = CompositeNewsProvider(finnhub=finnhub, gdelt=gdelt, yahoo=yahoo, naver=naver)
    items = await provider.fetch_news(ticker="AAPL", period="1M", region="US", top_n=5)

    assert len(items) == 1
    assert items[0].source == "finnhub"
    assert items[0].title == "Apple beats estimates"
    # 상위 소스에서 충분히 반환되면 fallback 소스는 호출되지 않는다.
    gdelt.fetch_articles.assert_not_called()
    yahoo.fetch_articles.assert_not_called()


@pytest.mark.asyncio
async def test_failover_falls_through_empty_source():
    finnhub = _stub_client([])
    gdelt = _stub_client(
        [
            {
                "date": "20260110",
                "title": "Global markets rally",
                "url": "https://g.example/1",
                "tone": 0.1,
            }
        ]
    )
    yahoo = _stub_client([])
    naver = MagicMock()

    provider = CompositeNewsProvider(finnhub=finnhub, gdelt=gdelt, yahoo=yahoo, naver=naver)
    items = await provider.fetch_news(ticker="AAPL", period="1M", region="US", top_n=5)

    assert len(items) == 1
    assert items[0].source == "gdelt"
    finnhub.fetch_articles.assert_called_once()
    gdelt.fetch_articles.assert_called_once()


@pytest.mark.asyncio
async def test_failover_timeout_moves_to_next_source(monkeypatch):
    async def _hang(*args, **kwargs):
        import asyncio
        await asyncio.sleep(10)
        return []

    slow_finnhub = MagicMock()
    slow_finnhub.fetch_articles = _hang
    gdelt = _stub_client(
        [
            {
                "date": "20260201",
                "title": "Fast source news",
                "url": "https://g.example/2",
                "tone": 0.0,
            }
        ]
    )
    yahoo = _stub_client([])
    naver = MagicMock()

    # 타임아웃을 짧게 설정해 테스트 속도 확보
    from app.infrastructure.config.settings import get_settings
    settings = get_settings()
    original = settings.history_news_per_source_timeout_s
    settings.history_news_per_source_timeout_s = 0.1
    try:
        provider = CompositeNewsProvider(
            finnhub=slow_finnhub, gdelt=gdelt, yahoo=yahoo, naver=naver,
        )
        items = await provider.fetch_news(
            ticker="AAPL", period="1M", region="US", top_n=5,
        )
    finally:
        settings.history_news_per_source_timeout_s = original

    assert len(items) == 1
    assert items[0].source == "gdelt"


@pytest.mark.asyncio
async def test_kr_region_starts_with_naver():
    finnhub = _stub_client([])
    gdelt = _stub_client([])
    yahoo = _stub_client([])

    naver = MagicMock()
    from app.domains.news.domain.entity.collected_news import CollectedNews
    naver.search = AsyncMock(
        return_value=[
            CollectedNews(
                title="삼성전자 실적 발표",
                description="요약 텍스트",
                url="https://n.example",
                published_at="Mon, 05 Jan 2026 10:00:00 +0900",
                keyword="005930",
            )
        ]
    )

    provider = CompositeNewsProvider(finnhub=finnhub, gdelt=gdelt, yahoo=yahoo, naver=naver)
    items = await provider.fetch_news(
        ticker="005930", period="1M", region="KR", top_n=5,
    )

    assert len(items) == 1
    assert items[0].source == "naver"
    naver.search.assert_called_once()
    finnhub.fetch_articles.assert_not_called()


def test_dedup_collapses_similar_titles_same_day():
    d = datetime.date(2026, 1, 1)
    items = [
        NewsItem(date=d, title="Apple beats estimates again", url="u1", source="finnhub"),
        NewsItem(date=d, title="Apple beats estimates", url="u2", source="gdelt"),  # 유사
        NewsItem(date=d, title="Tesla announces new factory", url="u3", source="yahoo"),
    ]
    kept = _dedup(items, threshold=0.6)
    assert len(kept) == 2
    sources = {k.source for k in kept}
    assert "finnhub" in sources
    assert "yahoo" in sources


def test_dedup_does_not_collapse_different_dates():
    items = [
        NewsItem(
            date=datetime.date(2026, 1, 1), title="Apple beats estimates",
            url="u1", source="finnhub",
        ),
        NewsItem(
            date=datetime.date(2026, 1, 2), title="Apple beats estimates",
            url="u2", source="gdelt",
        ),
    ]
    kept = _dedup(items, threshold=0.8)
    assert len(kept) == 2


def test_jaccard_similarity_case_insensitive():
    assert _jaccard_similarity("Apple Beats", "apple beats") == 1.0


def test_period_to_start_parses_tokens():
    # 오늘 기준 시작일 — 정확한 값이 아니라 형식만 확인
    start = _period_to_start("1M")
    today = datetime.date.today()
    delta = (today - start).days
    assert delta == 30


def test_period_to_start_falls_back_for_unknown():
    start = _period_to_start("10Y")  # 지원 안 함
    delta = (datetime.date.today() - start).days
    assert delta == 90  # _DEFAULT_PERIOD_DAYS
