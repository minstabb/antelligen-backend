"""이벤트 임팩트(abnormal return) 계산 + 저장 orchestration.

흐름:
  1. PendingEventForImpactQueryPort 로 AR 미계산/일부 누락 이벤트 식별
  2. ticker 별 그룹화 — 같은 ticker 의 여러 이벤트는 stock/benchmark bars 1회 조회 공유
  3. asset_type → BenchmarkResolver → benchmark ticker 결정 (None 이면 BENCHMARK_MISSING)
  4. AbnormalReturnCalculator 로 (post_days=5, post_days=20) 두 윈도우 계산
  5. EventImpactMetricRepositoryPort.upsert_bulk

bars 부족 / asset_type 미지원 케이스도 status 마킹된 metric 행을 저장한다 — 다음
실행 시 같은 이벤트를 반복 계산하는 것을 방지하기 위해.
"""
import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List

from app.domains.dashboard.application.port.out.asset_type_port import AssetTypePort
from app.domains.stock.market_data.application.port.out.daily_bar_repository_port import (
    DailyBarRepositoryPort,
)
from app.domains.stock.market_data.application.port.out.event_impact_metric_repository_port import (
    EventImpactMetricRepositoryPort,
)
from app.domains.stock.market_data.application.port.out.pending_event_for_impact_query_port import (
    PendingEventForImpact,
    PendingEventForImpactQueryPort,
)
from app.domains.stock.market_data.domain.entity.event_impact_metric import (
    EventImpactMetric,
)
from app.domains.stock.market_data.domain.service.abnormal_return_calculator import (
    AbnormalReturnCalculator,
)
from app.domains.stock.market_data.domain.service.benchmark_resolver import (
    BenchmarkResolver,
)
from app.domains.stock.market_data.domain.value_object.event_impact_status import (
    EventImpactStatus,
)

logger = logging.getLogger(__name__)

# (pre_days, post_days) 윈도우. plan default: ±5d, ±20d (pre_days 의미는 항상 -1).
_PRE_DAYS = -1
_POST_WINDOWS = (5, 20)

# AR 계산용 bars 조회 윈도우. ±20일을 거래일 기준 안전하게 커버.
_BARS_LOOKAROUND_BEFORE = 14
_BARS_LOOKAROUND_AFTER = 35


class ComputeEventImpactUseCase:

    def __init__(
        self,
        pending_query: PendingEventForImpactQueryPort,
        daily_bar_repository: DailyBarRepositoryPort,
        impact_repository: EventImpactMetricRepositoryPort,
        asset_type_port: AssetTypePort,
    ):
        self._pending_query = pending_query
        self._daily_bar_repository = daily_bar_repository
        self._impact_repository = impact_repository
        self._asset_type_port = asset_type_port

    async def execute(
        self,
        cutoff_date: date,
        event_types: List[str],
        limit: int = 1000,
    ) -> int:
        pending = await self._pending_query.find_pending(
            cutoff_date=cutoff_date, event_types=event_types, limit=limit
        )
        if not pending:
            logger.info("[ComputeEventImpact] pending 이벤트 없음")
            return 0

        by_ticker: Dict[str, List[PendingEventForImpact]] = defaultdict(list)
        for ev in pending:
            by_ticker[ev.ticker].append(ev)

        logger.info(
            "[ComputeEventImpact] 시작 — pending=%d unique tickers=%d",
            len(pending), len(by_ticker),
        )

        all_metrics: List[EventImpactMetric] = []
        bench_bars_cache: Dict[str, list] = {}

        for ticker, events in by_ticker.items():
            try:
                asset_type = await self._asset_type_port.get_quote_type(ticker)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ComputeEventImpact] asset_type 조회 실패 — UNKNOWN 처리: ticker=%s err=%s",
                    ticker, exc,
                )
                asset_type = "UNKNOWN"

            benchmark = BenchmarkResolver.resolve(ticker, asset_type)
            if benchmark is None:
                # 비-EQUITY 등 — 모든 윈도우를 BENCHMARK_MISSING 으로 마킹해 재계산 방지.
                for ev in events:
                    for post_days in _POST_WINDOWS:
                        all_metrics.append(
                            EventImpactMetric(
                                ticker=ev.ticker,
                                event_date=ev.event_date,
                                event_type=ev.event_type,
                                detail_hash=ev.detail_hash,
                                benchmark_ticker="",
                                pre_days=_PRE_DAYS,
                                post_days=post_days,
                                status=EventImpactStatus.BENCHMARK_MISSING.value,
                                sample_completeness=0.0,
                            )
                        )
                continue

            for ev in events:
                stock_bars = await self._daily_bar_repository.find_around(
                    ticker=ticker,
                    event_date=ev.event_date,
                    before_days=_BARS_LOOKAROUND_BEFORE,
                    after_days=_BARS_LOOKAROUND_AFTER,
                )
                if benchmark.ticker not in bench_bars_cache:
                    bench_bars_cache[benchmark.ticker] = []
                # 벤치마크 bars 도 이벤트 ±N일 기준으로 매번 조회 (same-ticker 호출은 동일 결과)
                bench_bars = await self._daily_bar_repository.find_around(
                    ticker=benchmark.ticker,
                    event_date=ev.event_date,
                    before_days=_BARS_LOOKAROUND_BEFORE,
                    after_days=_BARS_LOOKAROUND_AFTER,
                )

                bars_data_version = None
                if stock_bars:
                    bars_data_version = stock_bars[-1].bars_data_version

                for post_days in _POST_WINDOWS:
                    result = AbnormalReturnCalculator.compute(
                        stock_bars=stock_bars,
                        benchmark_bars=bench_bars,
                        event_date=ev.event_date,
                        post_days=post_days,
                    )
                    all_metrics.append(
                        EventImpactMetric(
                            ticker=ev.ticker,
                            event_date=ev.event_date,
                            event_type=ev.event_type,
                            detail_hash=ev.detail_hash,
                            benchmark_ticker=benchmark.ticker,
                            pre_days=_PRE_DAYS,
                            post_days=post_days,
                            status=result.status.value,
                            cumulative_return_pct=result.cumulative_return_pct,
                            benchmark_return_pct=result.benchmark_return_pct,
                            abnormal_return_pct=result.abnormal_return_pct,
                            sample_completeness=result.sample_completeness,
                            bars_data_version=bars_data_version,
                        )
                    )

        if not all_metrics:
            return 0

        saved = await self._impact_repository.upsert_bulk(all_metrics)
        ok_count = sum(1 for m in all_metrics if m.status == EventImpactStatus.OK.value)
        logger.info(
            "[ComputeEventImpact] 완료 — pending=%d metrics=%d ok=%d saved=%d",
            len(pending), len(all_metrics), ok_count, saved,
        )
        return saved
