from typing import Optional

from app.domains.company_profile.application.port.out.us_company_name_port import (
    UsCompanyNamePort,
)
from app.domains.disclosure.adapter.outbound.external.sec_edgar_api_client import (
    SecEdgarApiClient,
)


class SecCompanyNameAdapter(UsCompanyNamePort):
    """SEC EDGAR `company_tickers.json` 캐시를 통해 ticker → 회사명 변환.

    내부적으로 disclosure 도메인의 `SecEdgarApiClient` 를 재사용한다 (24h 메모리 캐시 공유).
    """

    def __init__(self, sec_client: SecEdgarApiClient) -> None:
        self._sec = sec_client

    async def resolve_company_name(self, ticker: str) -> Optional[str]:
        return await self._sec.resolve_company_name(ticker)
