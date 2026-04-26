"""한국 상장기업 ticker → 한글 회사명 룩업.

`schedule` 도메인의 `dart_corp_companies.COMPANIES` 데이터를 thin facade로 노출하여
다른 도메인(causality_agent 등)이 schedule 내부 구조에 의존하지 않고 사용할 수 있게 한다.
"""

from typing import Optional

from app.domains.schedule.adapter.outbound.external.dart_corp_companies import COMPANIES

_TICKER_TO_NAME: dict[str, str] = {meta.ticker: meta.name for meta in COMPANIES}


def lookup_korean_name(ticker: str) -> Optional[str]:
    """야후 형식(005930.KS) / 6자리 코드(005930) 모두 허용. 매칭 없으면 None."""
    if not ticker:
        return None
    code = ticker.upper().split(".")[0]
    return _TICKER_TO_NAME.get(code)
