"""_collect_news 한국 종목 분기 검증.

KR ticker → Naver 주 + GDELT(한글 키워드) 보조, Finnhub/yfinance 호출 0회.
비-KR ticker → 기존 Finnhub + GDELT 경로 유지 (회귀 가드).
"""

from datetime import date

import pytest

from app.domains.causality_agent.application.node import collect_non_economic_node as m


class _RecordingClient:
    """fetch_articles 호출 기록용 fake 클라이언트.

    monkeypatch로 클라이언트 클래스를 통째로 교체할 때 사용한다.
    """

    instances: list["_RecordingClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        type(self).instances.append(self)
        self.calls: list[tuple] = []

    async def fetch_articles(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value()

    @classmethod
    def return_value(cls):
        return []

    @classmethod
    def reset(cls):
        cls.instances = []


def _make_recording_client(name: str, return_articles: list | None = None):
    rv = list(return_articles or [])

    class _Cls(_RecordingClient):
        instances: list = []

        @classmethod
        def return_value(cls):
            return list(rv)

    _Cls.__name__ = name
    return _Cls


@pytest.mark.asyncio
async def test_korean_ticker_routes_to_naver_and_gdelt(monkeypatch):
    NaverFake = _make_recording_client(
        "NaverFake",
        return_articles=[{"date": "20260415", "title": "n1", "url": "u", "tone": 0.0, "source": "naver"}],
    )
    GdeltFake = _make_recording_client(
        "GdeltFake",
        return_articles=[{"date": "20260415", "title": "g1", "url": "u", "tone": 0.0, "source": "gdelt"}],
    )
    FinnhubFake = _make_recording_client("FinnhubFake")
    YahooFake = _make_recording_client("YahooFake")

    monkeypatch.setattr(m, "NaverKoreanNewsClient", NaverFake)
    monkeypatch.setattr(m, "GdeltClient", GdeltFake)
    monkeypatch.setattr(m, "FinnhubNewsClient", FinnhubFake)
    monkeypatch.setattr(m, "YahooFinanceNewsClient", YahooFake)

    result = await m._collect_news("005930.KS", date(2026, 4, 1), date(2026, 4, 30))

    assert len(NaverFake.instances) == 1
    assert len(NaverFake.instances[0].calls) == 1
    naver_args = NaverFake.instances[0].calls[0][0]
    assert naver_args[0] == "005930.KS"
    assert naver_args[1] == date(2026, 4, 1)
    assert naver_args[2] == date(2026, 4, 30)

    assert len(GdeltFake.instances) == 1
    gdelt_args = GdeltFake.instances[0].calls[0][0]
    assert gdelt_args[0] == "삼성전자"  # 한글 회사명 키워드

    assert FinnhubFake.instances == []
    assert YahooFake.instances == []

    sources = {a["source"] for a in result}
    assert sources == {"naver", "gdelt"}


@pytest.mark.asyncio
async def test_korean_ticker_falls_back_to_code_when_name_unknown(monkeypatch):
    """매핑에 없는 한국 6자리 코드는 ticker 그대로 GDELT 키워드."""
    NaverFake = _make_recording_client("NaverFake")
    GdeltFake = _make_recording_client("GdeltFake")
    FinnhubFake = _make_recording_client("FinnhubFake")
    YahooFake = _make_recording_client("YahooFake")

    monkeypatch.setattr(m, "NaverKoreanNewsClient", NaverFake)
    monkeypatch.setattr(m, "GdeltClient", GdeltFake)
    monkeypatch.setattr(m, "FinnhubNewsClient", FinnhubFake)
    monkeypatch.setattr(m, "YahooFinanceNewsClient", YahooFake)

    await m._collect_news("999999", date(2026, 4, 1), date(2026, 4, 30))

    gdelt_args = GdeltFake.instances[0].calls[0][0]
    assert gdelt_args[0] == "999999"
    assert FinnhubFake.instances == []


@pytest.mark.asyncio
async def test_us_equity_keeps_existing_finnhub_gdelt_path(monkeypatch):
    """비-KR 회귀 가드: AAPL → Finnhub + GDELT, Naver 호출 0회."""
    NaverFake = _make_recording_client("NaverFake")
    GdeltFake = _make_recording_client(
        "GdeltFake",
        return_articles=[{"date": "20260415", "title": "g1", "url": "u", "tone": 0.0, "source": "gdelt"}],
    )
    FinnhubFake = _make_recording_client(
        "FinnhubFake",
        return_articles=[{"date": "20260415", "title": "f1", "url": "u", "tone": 0.0, "source": "finnhub"}],
    )
    YahooFake = _make_recording_client("YahooFake")

    monkeypatch.setattr(m, "NaverKoreanNewsClient", NaverFake)
    monkeypatch.setattr(m, "GdeltClient", GdeltFake)
    monkeypatch.setattr(m, "FinnhubNewsClient", FinnhubFake)
    monkeypatch.setattr(m, "YahooFinanceNewsClient", YahooFake)

    result = await m._collect_news("AAPL", date(2026, 4, 1), date(2026, 4, 30))

    assert NaverFake.instances == []
    assert len(FinnhubFake.instances) == 1
    assert len(GdeltFake.instances) == 1
    assert YahooFake.instances == []  # finnhub/gdelt 가 결과 있어 fallback 미발동
    sources = {a["source"] for a in result}
    assert sources == {"finnhub", "gdelt"}


@pytest.mark.asyncio
async def test_index_ticker_keeps_existing_path(monkeypatch):
    """지수(^IXIC): Finnhub 스킵, GDELT만, Naver 호출 0회."""
    NaverFake = _make_recording_client("NaverFake")
    GdeltFake = _make_recording_client(
        "GdeltFake",
        return_articles=[{"date": "20260415", "title": "g1", "url": "u", "tone": 0.0, "source": "gdelt"}],
    )
    FinnhubFake = _make_recording_client("FinnhubFake")
    YahooFake = _make_recording_client("YahooFake")

    monkeypatch.setattr(m, "NaverKoreanNewsClient", NaverFake)
    monkeypatch.setattr(m, "GdeltClient", GdeltFake)
    monkeypatch.setattr(m, "FinnhubNewsClient", FinnhubFake)
    monkeypatch.setattr(m, "YahooFinanceNewsClient", YahooFake)

    await m._collect_news("^IXIC", date(2026, 4, 1), date(2026, 4, 30))

    assert NaverFake.instances == []
    assert FinnhubFake.instances == []
    assert len(GdeltFake.instances) == 1
    gdelt_args = GdeltFake.instances[0].calls[0][0]
    assert gdelt_args[0] == "NASDAQ Composite"
