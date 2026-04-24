import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Optional

from app.domains.dashboard.adapter.outbound.external.dart_announcement_client import (
    DartAnnouncementClient,
)
from app.domains.dashboard.application.port.out.sec_edgar_announcement_port import (
    SecEdgarAnnouncementPort,
)
from app.domains.dashboard.application.response.announcement_response import (
    AnnouncementEventResponse,
    AnnouncementsResponse,
)
from app.domains.dashboard.domain.service.announcement_collector import AnnouncementCollector

logger = logging.getLogger(__name__)

_PERIOD_TO_DAYS: dict[str, int] = {
    "1D": 365,
    "1W": 365 * 3,
    "1M": 365 * 5,
    "1Y": 365 * 20,
}

_KOREAN_TICKER_RE = re.compile(r"^\d{6}$")


def _is_korean_ticker(ticker: str) -> bool:
    return bool(_KOREAN_TICKER_RE.match(ticker))


class GetAnnouncementsUseCase:

    def __init__(
        self,
        sec_edgar_port: SecEdgarAnnouncementPort,
        dart_client: DartAnnouncementClient,
    ):
        self._sec_edgar_port = sec_edgar_port
        self._dart_client = dart_client
        self._collector = AnnouncementCollector()

    async def execute(
        self,
        ticker: str,
        period: str,
        corp_code: Optional[str] = None,
    ) -> AnnouncementsResponse:
        days = _PERIOD_TO_DAYS[period]
        start_date = date.today() - timedelta(days=days)
        end_date = date.today()

        async def _empty():
            return []

        if _is_korean_ticker(ticker):
            # 한국 종목 → DART만 사용
            dart_task = (
                self._dart_client.fetch_announcements(corp_code, start_date, end_date)
                if corp_code
                else _empty()
            )
            sec_task = _empty()
        else:
            # 미국 종목 → SEC EDGAR만 사용
            dart_task = _empty()
            sec_task = self._sec_edgar_port.fetch_announcements(ticker, start_date, end_date)

        dart_events, sec_events = await asyncio.gather(dart_task, sec_task)

        # DART 우선 병합 (한국은 dart_events만 있고 sec_events는 빔, 반대도 마찬가지)
        merged = self._collector.merge(dart_events, sec_events)

        logger.info(
            "[GetAnnouncements] ticker=%s, period=%s, dart=%d, sec=%d, merged=%d",
            ticker, period, len(dart_events), len(sec_events), len(merged),
        )

        return AnnouncementsResponse(
            ticker=ticker,
            period=period,
            count=len(merged),
            events=[AnnouncementEventResponse.from_entity(e) for e in merged],
        )
