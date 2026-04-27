"""_collect_announcements region 분기 검증 (OKR 1 P1.5).

KR ticker → DART 경로 (corp_code 매핑 후 DartAnnouncementClient).
US ticker → 기존 SEC EDGAR 경로 유지 (회귀 가드).
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.causality_agent.application.node import collect_non_economic_node as m


@pytest.mark.asyncio
async def test_us_ticker_takes_sec_path(monkeypatch):
    """미국 종목 (영문) → SEC EDGAR 호출, DART 경로 미진입."""
    sec_mock = MagicMock()
    sec_mock.fetch_announcements = AsyncMock(return_value=[])
    monkeypatch.setattr(
        m, "SecEdgarAnnouncementClient", lambda: sec_mock,
    )

    # DART 경로가 절대 호출되면 안 됨 — corp_code mapper / DART client 둘 다 호출 안 됨 검증
    dart_mapper_mock = AsyncMock()
    monkeypatch.setattr(
        "app.infrastructure.external.corp_code_mapper.ticker_to_corp_code",
        dart_mapper_mock,
    )

    result = await m._collect_announcements("AAPL", date(2024, 1, 1), date(2024, 1, 31))

    assert result == []
    sec_mock.fetch_announcements.assert_awaited_once()
    dart_mapper_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_kr_ticker_takes_dart_path(monkeypatch):
    """한국 종목 (.KS) → DART 경로, SEC 미호출."""
    sec_mock = MagicMock()
    sec_mock.fetch_announcements = AsyncMock()
    monkeypatch.setattr(
        m, "SecEdgarAnnouncementClient", lambda: sec_mock,
    )

    monkeypatch.setattr(
        "app.infrastructure.external.corp_code_mapper.ticker_to_corp_code",
        AsyncMock(return_value="00126380"),
    )

    fake_announcements = [
        {"date": "2024-01-15", "type": "TREASURY_STOCK", "title": "자기주식 취득결정",
         "source": "dart", "url": "https://dart.fss.or.kr/...", "items_str": None},
    ]
    dart_client_mock = MagicMock()
    dart_client_mock.fetch_announcements = AsyncMock(return_value=fake_announcements)
    monkeypatch.setattr(
        "app.domains.causality_agent.adapter.outbound.external.dart_announcement_client.DartAnnouncementClient",
        lambda: dart_client_mock,
    )

    result = await m._collect_announcements("005930.KS", date(2024, 1, 1), date(2024, 1, 31))

    assert result == fake_announcements
    sec_mock.fetch_announcements.assert_not_awaited()
    dart_client_mock.fetch_announcements.assert_awaited_once()


@pytest.mark.asyncio
async def test_kr_ticker_unmapped_returns_empty(monkeypatch):
    """corp_code 매핑 실패한 KR ticker → DART API 호출 없이 빈 배열."""
    sec_mock = MagicMock()
    monkeypatch.setattr(m, "SecEdgarAnnouncementClient", lambda: sec_mock)

    monkeypatch.setattr(
        "app.infrastructure.external.corp_code_mapper.ticker_to_corp_code",
        AsyncMock(return_value=None),  # 매핑 miss
    )

    dart_client_mock = MagicMock()
    dart_client_mock.fetch_announcements = AsyncMock()
    monkeypatch.setattr(
        "app.domains.causality_agent.adapter.outbound.external.dart_announcement_client.DartAnnouncementClient",
        lambda: dart_client_mock,
    )

    result = await m._collect_announcements("999999.KS", date(2024, 1, 1), date(2024, 1, 31))

    assert result == []
    dart_client_mock.fetch_announcements.assert_not_awaited()


@pytest.mark.asyncio
async def test_kr_ticker_dart_failure_returns_empty(monkeypatch):
    """DART API 예외 → graceful 빈 배열."""
    monkeypatch.setattr(
        "app.infrastructure.external.corp_code_mapper.ticker_to_corp_code",
        AsyncMock(return_value="00126380"),
    )

    dart_client_mock = MagicMock()
    dart_client_mock.fetch_announcements = AsyncMock(side_effect=RuntimeError("DART down"))
    monkeypatch.setattr(
        "app.domains.causality_agent.adapter.outbound.external.dart_announcement_client.DartAnnouncementClient",
        lambda: dart_client_mock,
    )

    result = await m._collect_announcements("005930.KS", date(2024, 1, 1), date(2024, 1, 31))

    assert result == []
