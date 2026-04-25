"""CollectImportantMacroEventsUseCase — 큐레이션 우선 + Top-N 컷 + 정렬."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.dashboard.application.response.economic_event_response import (
    EconomicEventResponse,
    EconomicEventsResponse,
)
from app.domains.history_agent.application.port.out.related_assets_port import (
    MacroContextEvent,
)
from app.domains.history_agent.application.usecase.collect_important_macro_events_usecase import (
    CollectImportantMacroEventsUseCase,
)
from app.domains.history_agent.domain.entity.curated_macro_event import CuratedMacroEvent

pytestmark = pytest.mark.asyncio


def _curated(date: datetime.date, title: str, score: float = 1.0) -> CuratedMacroEvent:
    return CuratedMacroEvent(
        date=date,
        event_type="CRISIS",
        region="US",
        title=title,
        detail=f"detail-{title}",
        tags=["crisis"],
        importance_score=score,
    )


def _fred_response() -> EconomicEventsResponse:
    events = [
        EconomicEventResponse(
            id="CPI-2024-01-01",
            type="CPI",
            label="CPI",
            date=datetime.date(2024, 1, 1),
            value=4.0,
            previous=3.5,
        )
    ]
    return EconomicEventsResponse(period="1Y", count=1, events=events)


def _context_event(date: datetime.date, kind: str = "VIX_SPIKE") -> MacroContextEvent:
    return MacroContextEvent(
        date=date,
        type=kind,  # type: ignore[arg-type]
        label="VIX 급등",
        detail="detail",
        change_pct=5.0,
        source="VIX",
    )


def _make_usecase(
    curated_events=None,
    fred_events=None,
    related_events=None,
    gpr_events=None,
) -> CollectImportantMacroEventsUseCase:
    curated_port = MagicMock()
    curated_port.fetch = AsyncMock(return_value=curated_events or [])

    related_port = MagicMock()
    related_port.fetch_significant_moves = AsyncMock(return_value=related_events or [])

    gpr_port = MagicMock()
    gpr_port.fetch_mom_spikes = AsyncMock(return_value=gpr_events or [])

    repo = MagicMock()
    repo.find_by_keys = AsyncMock(return_value=[])
    repo.upsert_bulk = AsyncMock(return_value=0)

    fred_port = MagicMock()

    uc = CollectImportantMacroEventsUseCase(
        fred_macro_port=fred_port,
        curated_port=curated_port,
        related_assets_port=related_port,
        gpr_index_port=gpr_port,
        enrichment_repo=repo,
    )
    uc._fred_events = fred_events or _fred_response()  # type: ignore[attr-defined]
    return uc


async def test_curated_always_preserved_and_sorted_first(monkeypatch):
    curated = [
        _curated(datetime.date(2020, 3, 15), "Fed 제로금리", 1.0),
        _curated(datetime.date(2022, 2, 24), "러·우크라 침공", 1.0),
    ]
    uc = _make_usecase(
        curated_events=curated,
        related_events=[_context_event(datetime.date(2024, 8, 5))],
    )

    with patch(
        "app.domains.history_agent.application.usecase.collect_important_macro_events_usecase.GetEconomicEventsUseCase"
    ) as MockEcon, patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm"
    ) as mock_llm_factory:
        econ_instance = MockEcon.return_value
        econ_instance.execute = AsyncMock(return_value=_fred_response())

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(content="[0.5, 0.6]"))
        mock_llm_factory.return_value = llm

        result = await uc.execute(region="US", period="5Y", top_n=10)

    # curated 먼저 (importance=1.0), 이후 LLM 점수 순
    assert result[0].importance_score == 1.0
    assert result[1].importance_score == 1.0
    assert all(e.importance_score is not None for e in result)


async def test_top_n_limits_output():
    curated = [_curated(datetime.date(2020, 1, i + 1), f"e{i}") for i in range(5)]
    uc = _make_usecase(curated_events=curated)

    with patch(
        "app.domains.history_agent.application.usecase.collect_important_macro_events_usecase.GetEconomicEventsUseCase"
    ) as MockEcon, patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm"
    ) as mock_llm_factory:
        econ_instance = MockEcon.return_value
        econ_instance.execute = AsyncMock(
            return_value=EconomicEventsResponse(period="1Y", count=0, events=[]),
        )
        mock_llm_factory.return_value = MagicMock()

        result = await uc.execute(region="US", period="1Y", top_n=3)

    assert len(result) == 3


async def test_dedupe_prefers_curated_over_fred_on_same_date_type():
    same_date = datetime.date(2024, 1, 1)
    curated = [
        CuratedMacroEvent(
            date=same_date,
            event_type="CPI",
            region="US",
            title="CPI 서프라이즈 (curated)",
            detail="curated detail",
            tags=[],
            importance_score=1.0,
        ),
    ]

    fred_events = EconomicEventsResponse(
        period="1Y",
        count=1,
        events=[
            EconomicEventResponse(
                id="CPI-2024-01-01",
                type="CPI",
                label="CPI",
                date=same_date,
                value=4.0,
                previous=3.5,
            )
        ],
    )
    uc = _make_usecase(curated_events=curated)

    with patch(
        "app.domains.history_agent.application.usecase.collect_important_macro_events_usecase.GetEconomicEventsUseCase"
    ) as MockEcon, patch(
        "app.domains.history_agent.application.service.macro_importance_ranker.get_workflow_llm"
    ) as mock_llm_factory:
        econ_instance = MockEcon.return_value
        econ_instance.execute = AsyncMock(return_value=fred_events)
        mock_llm_factory.return_value = MagicMock()

        result = await uc.execute(region="US", period="1Y", top_n=10)

    # curated 1건만 살아남아야 함
    cpi_events = [e for e in result if e.type == "CPI" and e.date == same_date]
    assert len(cpi_events) == 1
    assert cpi_events[0].title == "CPI 서프라이즈 (curated)"
