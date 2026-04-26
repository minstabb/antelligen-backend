from enum import Enum


class EventImpactStatus(str, Enum):
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"          # 거래일 부족 (이벤트 후 N일 미달)
    BENCHMARK_MISSING = "BENCHMARK_MISSING"          # 벤치마크 매핑 불가 (non-EQUITY 등)
    BENCHMARK_DATA_MISSING = "BENCHMARK_DATA_MISSING"  # 벤치마크 bars 미적재
    STOCK_DATA_MISSING = "STOCK_DATA_MISSING"        # 종목 bars 미적재
