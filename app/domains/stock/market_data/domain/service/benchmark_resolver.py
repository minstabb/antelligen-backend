from typing import Optional

from app.domains.stock.domain.service.market_region_resolver import (
    MarketRegionResolver,
)
from app.domains.stock.domain.value_object.market_region import MarketRegion
from app.domains.stock.market_data.domain.value_object.benchmark_ticker import (
    BenchmarkTicker,
)

# region별 단일 벤치마크 매핑.
# 섹터별(GICS) 정밀화는 follow-up.
_REGION_BENCHMARK: dict[str, BenchmarkTicker] = {
    "US": BenchmarkTicker(ticker="^GSPC", region="US"),
    "KR": BenchmarkTicker(ticker="^KS11", region="KR"),
}


def _market_region_to_str(mr: MarketRegion) -> Optional[str]:
    if mr in (MarketRegion.US_NASDAQ, MarketRegion.US_NYSE):
        return "US"
    if mr in (MarketRegion.KR_KOSPI, MarketRegion.KR_KOSDAQ, MarketRegion.KR_KONEX):
        return "KR"
    return None


class BenchmarkResolver:
    """ticker + asset_type → 시장 벤치마크.

    - asset_type != "EQUITY" 이면 None (INDEX/ETF/MUTUALFUND 는 abnormal return 의미가 다름)
    - region 추론 우선순위: 명시 region 인자 → MarketRegionResolver.resolve(ticker)
    - 매핑 누락 region → None
    """

    @staticmethod
    def resolve(
        ticker: str,
        asset_type: str,
        region: Optional[str] = None,
    ) -> Optional[BenchmarkTicker]:
        if (asset_type or "").upper() != "EQUITY":
            return None

        resolved_region = (region or "").upper() or _market_region_to_str(
            MarketRegionResolver.resolve(ticker)
        )
        if resolved_region is None:
            return None

        return _REGION_BENCHMARK.get(resolved_region)
