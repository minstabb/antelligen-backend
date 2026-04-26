"""NaverKoreanNewsClient 단위/통합 테스트.

httpx.AsyncClient 자체를 fake로 교체하여 외부 호출 없이 검증한다.
"""

from datetime import date, datetime, timezone

import httpx
import pytest

from app.domains.causality_agent.adapter.outbound.external import naver_korean_news_client as m
from app.domains.causality_agent.adapter.outbound.external.naver_korean_news_client import (
    NaverKoreanNewsClient,
    _parse_pub_date,
    _strip_html,
)


def test_parse_pub_date_rfc822():
    dt = _parse_pub_date("Mon, 25 Apr 2026 14:23:00 +0900")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 4 and dt.day == 25


def test_parse_pub_date_invalid_returns_none():
    assert _parse_pub_date("") is None
    assert _parse_pub_date("garbage-string") is None


def test_strip_html_removes_tags():
    assert _strip_html("<b>삼성전자</b> 호실적") == "삼성전자 호실적"
    assert _strip_html("plain") == "plain"


def test_normalize_items_filters_by_date_range():
    items = [
        {
            "title": "in-range",
            "originallink": "https://example.com/1",
            "pubDate": "Wed, 15 Apr 2026 10:00:00 +0900",
        },
        {
            "title": "too-old",
            "originallink": "https://example.com/2",
            "pubDate": "Sat, 01 Mar 2026 10:00:00 +0900",
        },
        {
            "title": "too-new",
            "originallink": "https://example.com/3",
            "pubDate": "Wed, 06 May 2026 10:00:00 +0900",
        },
    ]
    out, oldest = NaverKoreanNewsClient._normalize_items(
        items, date(2026, 4, 1), date(2026, 4, 30)
    )
    assert len(out) == 1
    assert out[0]["title"] == "in-range"
    assert out[0]["source"] == "naver"
    assert out[0]["url"] == "https://example.com/1"
    assert out[0]["date"] == "20260415"
    # oldest 는 sort=date 종료조건 판정에 쓰임 — 페이지에서 본 모든 항목 중 최오래
    assert oldest is not None
    assert oldest.astimezone(timezone.utc) <= datetime(2026, 3, 1, 12, tzinfo=timezone.utc)


def test_normalize_items_skips_missing_pubdate_and_url():
    items = [
        {"title": "no-pubdate", "link": "https://x"},
        {"title": "no-url", "pubDate": "Wed, 15 Apr 2026 10:00:00 +0900"},
    ]
    out, oldest = NaverKoreanNewsClient._normalize_items(
        items, date(2026, 4, 1), date(2026, 4, 30)
    )
    assert out == []


@pytest.mark.asyncio
async def test_fetch_articles_returns_empty_when_credentials_missing(monkeypatch):
    class _FakeSettings:
        naver_client_id = ""
        naver_client_secret = ""

    monkeypatch.setattr(m, "get_settings", lambda: _FakeSettings())

    result = await NaverKoreanNewsClient().fetch_articles(
        "005930.KS", date(2026, 4, 1), date(2026, 4, 30)
    )
    assert result == []


@pytest.mark.asyncio
async def test_fetch_articles_uses_korean_name_keyword_and_filters(monkeypatch):
    """삼성전자(005930) → keyword='삼성전자' 로 호출 + pubDate 범위 외 컷."""
    captured_params: list[dict] = []

    response_payload = {
        "items": [
            {
                "title": "<b>삼성전자</b> 1Q 호실적",
                "originallink": "https://news.example/1",
                "pubDate": "Wed, 15 Apr 2026 10:00:00 +0900",
            },
            {
                "title": "삼성전자 너무 오래된 뉴스",
                "originallink": "https://news.example/2",
                "pubDate": "Sat, 01 Jan 2026 10:00:00 +0900",
            },
        ]
    }

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return response_payload

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            captured_params.append(params or {})
            return _FakeResponse()

    class _FakeSettings:
        naver_client_id = "id"
        naver_client_secret = "secret"

    monkeypatch.setattr(m, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = await NaverKoreanNewsClient().fetch_articles(
        "005930.KS", date(2026, 4, 1), date(2026, 4, 30)
    )

    assert captured_params, "Naver API 호출이 발생해야 함"
    assert captured_params[0]["query"] == "삼성전자"
    assert captured_params[0]["sort"] == "date"
    assert len(result) == 1
    assert result[0]["title"] == "삼성전자 1Q 호실적"
    assert result[0]["source"] == "naver"


@pytest.mark.asyncio
async def test_fetch_articles_falls_back_to_ticker_when_name_unknown(monkeypatch):
    """매핑에 없는 한국 종목 코드는 6자리 코드 그대로 검색."""
    captured_params: list[dict] = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"items": []}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            captured_params.append(params or {})
            return _FakeResponse()

    class _FakeSettings:
        naver_client_id = "id"
        naver_client_secret = "secret"

    monkeypatch.setattr(m, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    await NaverKoreanNewsClient().fetch_articles(
        "999999", date(2026, 4, 1), date(2026, 4, 30)
    )

    assert captured_params[0]["query"] == "999999"
