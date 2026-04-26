from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkTicker:
    """종목/지역 → 시장 벤치마크 매핑 결과.

    - region: "US" | "KR"
    - ticker: 해당 region의 대표 시장 지수 (^GSPC / ^KS11)
    """

    ticker: str
    region: str
