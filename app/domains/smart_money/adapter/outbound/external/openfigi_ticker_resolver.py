import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_BATCH_SIZE = 10  # 인증 없이 요청당 최대 10개

# 자주 등장하는 CUSIP → 티커 하드코딩 맵 (API 호출 절감)
_CUSIP_TICKER_CACHE: dict[str, str] = {
    "037833100": "AAPL",
    "594918104": "MSFT",
    "02079K305": "GOOGL",
    "023135106": "AMZN",
    "67066G104": "NVDA",
    "46090E103": "META",
    "88160R101": "TSLA",
    "30303M102": "META",
    "02005N100": "ALLY",
    "166764100": "CVX",
    "084670702": "BRK.B",
    "912828YP1": "TLT",
    "191216100": "KO",
    "34959J108": "FDX",
    "438516106": "HON",
    "49128V206": "KHDI",
    "808513105": "SCHW",
    "92826C839": "V",
    "14912E105": "C",
    "172967424": "C",
    "025816109": "AXP",
    "40434L105": "HPQ",
    "254687106": "DVA",
    "233046102": "DAL",
    "38141G104": "GS",
    "69351T106": "PNC",
    "532457108": "LPX",
    "345370860": "FHN",
}


async def resolve_tickers_batch(cusips: list[str]) -> dict[str, Optional[str]]:
    """CUSIP 리스트를 OpenFIGI API로 일괄 조회하여 {cusip: ticker} 맵을 반환한다."""
    result: dict[str, Optional[str]] = {}

    # 캐시에 있는 것 먼저 처리
    to_fetch = []
    for cusip in cusips:
        if cusip in _CUSIP_TICKER_CACHE:
            result[cusip] = _CUSIP_TICKER_CACHE[cusip]
        else:
            to_fetch.append(cusip)

    if not to_fetch:
        return result

    # 배치로 OpenFIGI 호출
    for i in range(0, len(to_fetch), _BATCH_SIZE):
        batch = to_fetch[i: i + _BATCH_SIZE]
        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    _OPENFIGI_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning("[openfigi] HTTP %s — 배치 %d 스킵", resp.status_code, i)
                    for c in batch:
                        result[c] = None
                    continue

                data = resp.json()
                for cusip, item in zip(batch, data):
                    figi_data = item.get("data")
                    if figi_data:
                        ticker = figi_data[0].get("ticker")
                        result[cusip] = ticker
                        if ticker:
                            _CUSIP_TICKER_CACHE[cusip] = ticker
                    else:
                        result[cusip] = None
        except Exception as exc:
            logger.warning("[openfigi] 배치 %d 조회 실패: %s", i, exc)
            for c in batch:
                result[c] = None

    return result
