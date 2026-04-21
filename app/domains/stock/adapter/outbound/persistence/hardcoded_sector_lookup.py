from app.domains.agent.domain.value_object.sector import Sector
from app.domains.stock.application.port.sector_lookup_port import SectorLookupPort

# 엔터테인먼트 종목 시드 (추후 CSV 이관 가능)
_ENTERTAINMENT_TICKERS: frozenset[str] = frozenset({
    "352820",  # HYBE
    "041510",  # SM엔터테인먼트
    "035900",  # JYP Ent.
    "122870",  # YG엔터테인먼트
    "041060",  # CJ ENM
    "068270",  # 셀트리온 — 제외 가능, 여기선 예시
})

# 섹터별 티커 매핑 (확장 가능 구조)
_SECTOR_MAP: dict[str, Sector] = {t: Sector.ENTERTAINMENT for t in _ENTERTAINMENT_TICKERS}


class HardcodedSectorLookup(SectorLookupPort):
    """초기 시드 기반 섹터 조회 (CSV/DB 이관 전 Phase 1 구현)"""

    async def get_sector(self, ticker: str) -> Sector:
        return _SECTOR_MAP.get(ticker, Sector.UNKNOWN)
