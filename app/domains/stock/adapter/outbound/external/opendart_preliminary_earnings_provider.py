import logging
from datetime import date, timedelta
from typing import Optional

from app.domains.disclosure.adapter.outbound.external.dart_disclosure_api_client import DartDisclosureApiClient
from app.domains.stock.application.port.preliminary_earnings_port import PreliminaryEarningsPort
from app.domains.stock.domain.value_object.earnings_release import EarningsRelease

logger = logging.getLogger(__name__)

_PRELIMINARY_KEYWORDS = ("영업(잠정)실적", "잠정실적", "잠정 실적")


class OpenDartPreliminaryEarningsProvider(PreliminaryEarningsPort):
    """DART 공시 목록에서 영업(잠정)실적을 찾는 어댑터"""

    def __init__(self) -> None:
        self._dart = DartDisclosureApiClient()

    async def fetch_latest_preliminary(
        self,
        corp_code: str,
        within_days: int = 120,
    ) -> Optional[EarningsRelease]:
        today = date.today()
        bgn = (today - timedelta(days=within_days)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")

        try:
            result = await self._dart.fetch_disclosure_list(
                bgn_de=bgn,
                end_de=end,
                corp_code=corp_code,
            )
        except Exception as e:
            logger.warning("[잠정실적] DART 조회 실패 corp_code=%s: %s", corp_code, e)
            return None

        # 잠정실적 키워드를 포함한 공시만 필터
        preliminary = [
            item for item in result.items
            if any(kw in item.report_nm for kw in _PRELIMINARY_KEYWORDS)
        ]

        if not preliminary:
            return None

        # 접수일(rcept_dt) 기준 최신 1건
        latest = sorted(preliminary, key=lambda x: x.rcept_dt, reverse=True)[0]

        report_date = None
        try:
            report_date = date(
                int(latest.rcept_dt[:4]),
                int(latest.rcept_dt[4:6]),
                int(latest.rcept_dt[6:8]),
            )
        except (ValueError, IndexError):
            pass

        return EarningsRelease(
            ticker="",  # 호출측에서 채움
            report_date=report_date,
            is_preliminary=True,
            source="DART",
            title=latest.report_nm,
        )
