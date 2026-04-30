import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.common.exception.app_exception import AppException
from app.domains.schedule.application.port.out.economic_event_repository_port import (
    EconomicEventRepositoryPort,
)
from app.domains.schedule.application.port.out.event_impact_analysis_repository_port import (
    EventImpactAnalysisRepositoryPort,
)
from app.domains.schedule.application.port.out.event_impact_analyzer_port import (
    EventImpactAnalyzerPort,
)
from app.domains.schedule.application.port.out.investment_info_provider_port import (
    InvestmentInfoProviderPort,
)
from app.domains.schedule.application.port.out.schedule_notification_publisher_port import (
    ScheduleNotificationPublisherPort,
)
from app.domains.schedule.domain.entity.schedule_notification import ScheduleNotification
from app.domains.schedule.application.request.run_event_analysis_request import (
    RunEventAnalysisRequest,
)
from app.domains.schedule.application.response.event_impact_analysis_response import (
    EventImpactAnalysisItem,
    RunEventAnalysisResponse,
    UpcomingEventItem,
)
from app.domains.schedule.domain.entity.economic_event import EconomicEvent
from app.domains.schedule.domain.entity.event_impact_analysis import EventImpactAnalysis
from app.domains.schedule.domain.service.us_event_title_translator import (
    translate_us_event_title,
)
from app.domains.schedule.domain.value_object.event_importance import EventImportance
from app.domains.schedule.domain.value_object.investment_info_type import InvestmentInfoType

logger = logging.getLogger(__name__)

# 분석 파이프라인에서 제외할 이벤트 source (표시 전용)
_ANALYSIS_EXCLUDED_SOURCES = {"corp_earnings"}

# 다가오는 일정 조회 범위 (기준일 +1 ~ +N 일)
_UPCOMING_WINDOW_DAYS = 7

# FOMC 회의 1건을 가리키는 동의어 패턴 (대소문자 무시).
# (source, source_event_id) 가 다르더라도 같은 (country, date) 에서 이 패턴 중
# 하나가 매칭되면 동일 사건으로 간주해 1건만 노출한다.
# 과거 잘못된 sync 로 DB 에 남아 있는 중복 row 와 향후 새 source 가 추가될 때를
# 대비한 런타임 safety-net.
_FOMC_TOPIC_PATTERNS = (
    "fomc",
    "federal open market committee",
    "기준금리",  # central_bank source 의 한글 타이틀
    "summary of economic projections",
    "projections materials",
)

# topic dedup 시 우선 보존할 source 우선순위 (앞쪽이 캐노니컬)
_DEDUP_SOURCE_PRIORITY = ("central_bank", "snapshot", "fred", "corp_earnings")


def _is_fomc_topic(title: str) -> bool:
    if not title:
        return False
    lowered = title.lower()
    return any(p in lowered for p in _FOMC_TOPIC_PATTERNS)


def _source_rank(source: str) -> int:
    try:
        return _DEDUP_SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(_DEDUP_SOURCE_PRIORITY)


def _dedupe_overlapping_events(events: List[EconomicEvent]) -> List[EconomicEvent]:
    """같은 (country, date) 에 동일 토픽(현재는 FOMC) 이벤트가 다수 있으면 1건으로 collapse.

    선택 규칙:
      1) `_DEDUP_SOURCE_PRIORITY` 가 앞쪽인 source 가 우선 (central_bank > fred 등)
      2) source 가 같으면 importance HIGH 우선
      3) 그래도 같으면 source_event_id 기준 사전순으로 결정 (deterministic)
    """
    if not events:
        return events

    grouped: Dict[tuple, List[EconomicEvent]] = {}
    leftovers: List[EconomicEvent] = []

    for e in events:
        if _is_fomc_topic(e.title):
            key = ("FOMC", e.country, e.event_at.date())
            grouped.setdefault(key, []).append(e)
        else:
            leftovers.append(e)

    deduped: List[EconomicEvent] = list(leftovers)
    for key, group in grouped.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        group.sort(
            key=lambda e: (
                _source_rank(e.source),
                0 if e.importance == EventImportance.HIGH else 1,
                e.source_event_id or "",
            )
        )
        chosen = group[0]
        dropped_titles = [f"{e.source}:{e.title}" for e in group[1:]]
        print(
            f"[schedule.analyze] FOMC 중복 collapse country={key[1]} date={key[2]} "
            f"chosen={chosen.source}:{chosen.title!r} dropped={dropped_titles}"
        )
        deduped.append(chosen)

    deduped.sort(key=lambda e: e.event_at)
    return deduped


def annotate_duplicate_titles(items: list, title_attr: str, country_attr: str) -> None:
    """같은 (title, country) 가 2건 이상이면 각 title 끝에 ' (M/D)' 를 붙여 식별 가능하게 한다.

    같은 release 가 한 달에 2번 발표(예: Chicago Fed Advance Retail Trade Summary 의
    월초·월중)되어 응답 윈도우 안에 같은 title 2건이 들어왔을 때 화면이 중복으로
    보이는 것을 방지한다. 1건이면 손대지 않는다.
    """
    if not items:
        return
    groups: Dict[tuple, list] = defaultdict(list)
    for it in items:
        title = (getattr(it, title_attr) or "").strip()
        country = getattr(it, country_attr)
        groups[(title, country)].append(it)
    for group in groups.values():
        if len(group) <= 1:
            continue
        for it in group:
            ev_at = getattr(it, "event_at")
            md = f"{ev_at.month}/{ev_at.day}"
            current = getattr(it, title_attr) or ""
            setattr(it, title_attr, f"{current} ({md})")


# 프론트 '다가오는 경제 일정' 섹션 하단 안내 문구
UPCOMING_EVENTS_NOTICE = (
    "코스피200, 코스닥150, 코리아 밸류업 지수 해당 기업들의 잠정 실적 공시를 포함합니다."
)

# 모든 일정에 공통으로 붙일 '핵심 매크로 변수' + 위험자산 세트
_DEFAULT_INDICATORS: List[InvestmentInfoType] = [
    # 금리·수익률 곡선
    InvestmentInfoType.INTEREST_RATE,     # 미 10년물
    InvestmentInfoType.US_T2Y,            # 미 2년물
    InvestmentInfoType.US_T20Y,           # 미 20년물
    # 원자재·안전자산
    InvestmentInfoType.OIL_PRICE,         # WTI
    InvestmentInfoType.GOLD,
    # 환율
    InvestmentInfoType.EXCHANGE_RATE,     # USD/KRW
    InvestmentInfoType.USD_JPY,
    InvestmentInfoType.DXY,
    # 변동성
    InvestmentInfoType.VIX,
    # 위험자산
    InvestmentInfoType.SP_500,
    InvestmentInfoType.NASDAQ_100,
    InvestmentInfoType.KOSPI_200,
]


class RunEventImpactAnalysisUseCase:
    def __init__(
        self,
        event_repository: EconomicEventRepositoryPort,
        analysis_repository: EventImpactAnalysisRepositoryPort,
        indicator_provider: InvestmentInfoProviderPort,
        analyzer: EventImpactAnalyzerPort,
        model_name: str,
        notification_publisher: Optional[ScheduleNotificationPublisherPort] = None,
    ):
        self._event_repository = event_repository
        self._analysis_repository = analysis_repository
        self._indicator_provider = indicator_provider
        self._analyzer = analyzer
        self._model_name = model_name
        self._notification_publisher = notification_publisher

    async def execute(self, request: RunEventAnalysisRequest) -> RunEventAnalysisResponse:
        today = date.today()
        reference_date, is_weekend_shifted = self._resolve_reference_date(today)
        start = reference_date - timedelta(days=request.days_back)
        end = reference_date + timedelta(days=request.days_forward)
        importance_set = {lvl.upper() for lvl in request.importance_levels}

        if is_weekend_shifted:
            print(
                f"[schedule.analyze] ▶ 주말 감지 today={today.isoformat()} "
                f"({today.strftime('%A')}) → reference={reference_date.isoformat()} (금요일) 로 시프트"
            )
        print(
            f"[schedule.analyze] ▶ 시작 reference={reference_date.isoformat()} "
            f"range={start.isoformat()}~{end.isoformat()} "
            f"importance={sorted(importance_set)} country={request.country or '*'} "
            f"limit={request.limit} force_refresh={request.force_refresh}"
        )

        # 1) 대상 경제 일정 조회 (중요도 필터는 in-memory 로 적용)
        events_all = await self._event_repository.find_by_range(
            start=start,
            end=end,
            country=request.country,
            importance=None,  # 다중 importance 필터는 여기서 수행
        )
        # 중요도 필터 + 표시 전용 소스(기업 잠정실적 등) 분석 제외
        events = [
            e
            for e in events_all
            if e.importance.value in importance_set
            and e.source not in _ANALYSIS_EXCLUDED_SOURCES
        ]
        # 같은 (country, date) FOMC 동의 이벤트는 1건으로 collapse — DB 에 잔존하는
        # 과거 중복 row 가 화면을 어지럽히지 않도록 런타임 safety-net
        events = _dedupe_overlapping_events(events)
        # 기준일(reference_date) 기준 가까운 날짜부터 처리
        events.sort(key=lambda e: abs((e.event_at.date() - reference_date).days))
        events = events[: request.limit]

        if not events:
            print(
                "[schedule.analyze] 대상 경제 일정 없음 → 일일 매크로 스냅샷 가상 이벤트로 분석 진행"
            )
            snapshot_event = await self._ensure_daily_snapshot_event(reference_date)
            events = [snapshot_event]

        # 2) 공통 매크로 지표 스냅샷 1회 수집
        try:
            snapshot = await self._build_indicator_snapshot()
        except Exception as exc:
            print(f"[schedule.analyze]   ❌ 지표 스냅샷 수집 실패: {exc}")
            logger.exception("[schedule.analyze] 지표 스냅샷 수집 실패: %s", exc)
            raise AppException(
                status_code=502,
                message=f"외부 매크로 지표 수집에 실패했습니다: {exc}",
            ) from exc

        # 3) 기존 분석 조회 → force_refresh=False 면 스킵
        event_ids = [e.id for e in events if e.id is not None]
        existing_list = await self._analysis_repository.find_by_event_ids(event_ids)
        existing_by_id = {a.event_id: a for a in existing_list}

        items: List[EventImpactAnalysisItem] = []
        analyzed = 0
        skipped = 0
        failed = 0

        for event in events:
            if event.id in existing_by_id and not request.force_refresh:
                print(
                    f"[schedule.analyze]   · skip(existing) event_id={event.id} "
                    f"title={event.title[:30]!r}"
                )
                skipped += 1
                items.append(self._to_item(event, existing_by_id[event.id]))
                continue

            try:
                result = await self._analyzer.analyze(event, snapshot)
                now = datetime.now(timezone.utc)
                analysis = EventImpactAnalysis(
                    event_id=event.id,
                    summary=result.summary,
                    direction=result.direction,
                    impact_tags=list(result.impact_tags),
                    key_drivers=list(result.key_drivers),
                    risks=list(result.risks),
                    indicator_snapshot=snapshot,
                    model_name=self._model_name,
                    generated_at=now,
                    updated_at=now,
                )
                saved = await self._analysis_repository.upsert(analysis)
                analyzed += 1
                items.append(self._to_item(event, saved))
                await self._emit_notification(
                    event=event,
                    success=True,
                    analysis_id=saved.id,
                    stored_at=saved.updated_at or saved.generated_at or now,
                    error_message="",
                )
            except Exception as exc:
                failed += 1
                print(
                    f"[schedule.analyze]   ❌ 분석 실패 event_id={event.id}: {exc}"
                )
                logger.exception(
                    "[schedule.analyze] event_id=%s 분석 실패: %s", event.id, exc
                )
                await self._emit_notification(
                    event=event,
                    success=False,
                    analysis_id=None,
                    stored_at=datetime.now(timezone.utc),
                    error_message=str(exc),
                )
                continue

        # 다가오는 일주일 경제 일정 (reference_date 익일 ~ +7일)
        upcoming = await self._fetch_upcoming_events(reference_date)

        # 같은 (title, country) 가 윈도우 내 2건 이상이면 ' (M/D)' suffix 로 식별 가능하게
        annotate_duplicate_titles(items, "event_title", "event_country")

        print(
            f"[schedule.analyze] ■ 완료 total={len(events)} analyzed={analyzed} "
            f"skipped={skipped} failed={failed} upcoming_7d={len(upcoming)}"
        )

        return RunEventAnalysisResponse(
            total_events=len(events),
            analyzed_count=analyzed,
            skipped_existing=skipped,
            failed_count=failed,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            reference_date=reference_date,
            today=today,
            is_weekend_shifted=is_weekend_shifted,
            items=items,
            upcoming_events=upcoming,
            upcoming_events_notice=UPCOMING_EVENTS_NOTICE,
        )

    @staticmethod
    def _resolve_reference_date(today: date) -> tuple[date, bool]:
        """토/일이면 직전 금요일로 시프트. weekday(): Mon=0..Fri=4, Sat=5, Sun=6."""
        wd = today.weekday()
        if wd == 5:  # 토요일
            return today - timedelta(days=1), True
        if wd == 6:  # 일요일
            return today - timedelta(days=2), True
        return today, False

    async def _fetch_upcoming_events(self, reference_date: date) -> List[UpcomingEventItem]:
        start = reference_date + timedelta(days=1)
        end = reference_date + timedelta(days=_UPCOMING_WINDOW_DAYS)
        try:
            events = await self._event_repository.find_by_range(start=start, end=end)
        except Exception as exc:
            print(f"[schedule.analyze]   ⚠ 다가오는 일정 조회 실패: {exc}")
            logger.warning("[schedule.analyze] 다가오는 일정 조회 실패: %s", exc)
            return []

        # 같은 (country, date) FOMC 동의 이벤트 collapse
        events = _dedupe_overlapping_events(events)
        print(
            f"[schedule.analyze] 다가오는 1주일 일정 {len(events)}건 "
            f"({start.isoformat()}~{end.isoformat()})"
        )
        events.sort(key=lambda e: e.event_at)
        upcoming_items = [
            UpcomingEventItem(
                event_id=e.id,
                title=translate_us_event_title(e.title) if e.country == "US" else e.title,
                country=e.country,
                event_at=e.event_at,
                importance=e.importance.value,
                source=e.source,
                reference_url=e.reference_url,
            )
            for e in events
            if e.id is not None
        ]
        annotate_duplicate_titles(upcoming_items, "title", "country")
        return upcoming_items

    async def _ensure_daily_snapshot_event(self, today: date) -> EconomicEvent:
        """경제 일정이 없을 때 사용할 '일일 매크로 스냅샷' 가상 이벤트를 생성/조회.

        source='snapshot', source_event_id='daily-<yyyy-mm-dd>' 형태로 UNIQUE
        제약을 이용해 하루 1건만 존재하도록 보장한다.
        """
        source = "snapshot"
        source_event_id = f"daily-{today.isoformat()}"

        existing = await self._event_repository.find_by_source_key(source, source_event_id)
        if existing is not None:
            print(
                f"[schedule.analyze]   · 기존 일일 스냅샷 이벤트 재사용 id={existing.id}"
            )
            return existing

        placeholder = EconomicEvent(
            source=source,
            source_event_id=source_event_id,
            title=f"일일 매크로 스냅샷 ({today.isoformat()})",
            country="GLOBAL",
            event_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
            importance=EventImportance.MEDIUM,
            description="경제 일정이 없는 날의 핵심 변수(금리·유가·환율 등) 스냅샷 분석용 가상 이벤트",
            reference_url=None,
        )
        await self._event_repository.save_all([placeholder])
        saved = await self._event_repository.find_by_source_key(source, source_event_id)
        if saved is None:
            raise RuntimeError("일일 스냅샷 이벤트 저장 후 재조회에 실패했습니다.")
        print(
            f"[schedule.analyze]   · 일일 스냅샷 이벤트 신규 생성 id={saved.id} "
            f"date={today.isoformat()}"
        )
        return saved

    async def _emit_notification(
        self,
        event,
        success: bool,
        analysis_id,
        stored_at,
        error_message: str,
    ) -> None:
        if self._notification_publisher is None:
            return
        try:
            notification = ScheduleNotification(
                event_id=event.id,
                event_title=event.title,
                analysis_id=analysis_id,
                success=success,
                stored_at=stored_at,
                error_message=error_message or "",
            )
            await self._notification_publisher.publish(notification)
        except Exception as exc:
            print(f"[schedule.analyze]   ⚠ 알림 발행 실패 event_id={event.id}: {exc}")
            logger.exception(
                "[schedule.analyze] 알림 발행 실패 event_id=%s: %s", event.id, exc
            )

    async def _build_indicator_snapshot(self) -> Dict[str, Any]:
        """핵심 변수들을 병렬로 수집해 {type_value: info_dict} 형태로 반환."""
        async def _fetch(info_type: InvestmentInfoType):
            try:
                info = await self._indicator_provider.fetch(info_type)
                return info_type, {
                    "display_name": info_type.display_name,
                    "symbol": info.symbol,
                    "value": info.value,
                    "unit": info.unit,
                    "source": info.source,
                    "retrieved_at": info.retrieved_at.isoformat(),
                }
            except Exception as exc:
                print(f"[schedule.analyze]   · 지표 {info_type.value} 수집 실패: {exc}")
                logger.warning("[schedule.analyze] 지표 %s 실패: %s", info_type.value, exc)
                return info_type, None

        results = await asyncio.gather(*(_fetch(t) for t in _DEFAULT_INDICATORS))
        snapshot: Dict[str, Any] = {}
        for info_type, info in results:
            if info is not None:
                snapshot[info_type.value] = info

        if not snapshot:
            raise RuntimeError("모든 지표 수집에 실패했습니다.")

        print(f"[schedule.analyze] 지표 스냅샷 = {list(snapshot.keys())}")
        return snapshot

    @staticmethod
    def _to_item(
        event: EconomicEvent, analysis: EventImpactAnalysis
    ) -> EventImpactAnalysisItem:
        display_title = (
            translate_us_event_title(event.title)
            if event.country == "US"
            else event.title
        )
        return EventImpactAnalysisItem(
            id=analysis.id,
            event_id=analysis.event_id,
            event_title=display_title,
            event_country=event.country,
            event_at=event.event_at,
            event_importance=event.importance.value,
            summary=analysis.summary,
            direction=analysis.direction,
            impact_tags=list(analysis.impact_tags),
            key_drivers=list(analysis.key_drivers),
            risks=list(analysis.risks),
            indicator_snapshot=dict(analysis.indicator_snapshot),
            model_name=analysis.model_name,
            generated_at=analysis.generated_at,
            updated_at=analysis.updated_at,
        )
