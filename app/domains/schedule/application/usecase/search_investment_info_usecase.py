import asyncio
import logging
from typing import List

from app.common.exception.app_exception import AppException
from app.domains.schedule.application.port.out.investment_info_provider_port import (
    InvestmentInfoProviderPort,
)
from app.domains.schedule.application.request.search_investment_info_request import (
    SearchInvestmentInfoRequest,
)
from app.domains.schedule.application.response.investment_info_response import (
    InvestmentInfoItem,
    SearchInvestmentInfoResponse,
)
from app.domains.schedule.domain.entity.investment_info import InvestmentInfo
from app.domains.schedule.domain.value_object.investment_info_type import InvestmentInfoType

logger = logging.getLogger(__name__)


class SearchInvestmentInfoUseCase:
    def __init__(self, provider: InvestmentInfoProviderPort):
        self._provider = provider

    async def execute(self, request: SearchInvestmentInfoRequest) -> SearchInvestmentInfoResponse:
        print(f"[schedule.usecase] ▶ 요청 types={request.types}")

        if not request.types:
            raise AppException(
                status_code=400,
                message="조회할 투자 정보 유형을 하나 이상 지정해야 합니다.",
            )

        # 1) 입력 유형 정규화 + 중복 제거. 지원하지 않는 유형은 400 으로 반환.
        resolved: List[InvestmentInfoType] = []
        seen = set()
        for raw in request.types:
            try:
                info_type = InvestmentInfoType.parse(raw)
            except ValueError as exc:
                raise AppException(
                    status_code=400,
                    message=(
                        f"지원하지 않는 투자 정보 유형입니다: '{raw}'. "
                        f"지원되는 값: {', '.join(InvestmentInfoType.supported())}"
                    ),
                ) from exc
            if info_type not in seen:
                seen.add(info_type)
                resolved.append(info_type)

        print(f"[schedule.usecase] 정규화된 유형 = {[t.value for t in resolved]}")

        # 2) 병렬 조회
        results = await asyncio.gather(
            *(self._safe_fetch(t) for t in resolved),
            return_exceptions=False,
        )

        items = [self._to_item(info) for info in results]
        print(f"[schedule.usecase] ■ 응답 {len(items)}건")
        return SearchInvestmentInfoResponse(items=items)

    async def _safe_fetch(self, info_type: InvestmentInfoType) -> InvestmentInfo:
        try:
            info = await self._provider.fetch(info_type)
            print(
                f"[schedule.usecase]   ✓ {info_type.value} value={info.value} "
                f"unit={info.unit}"
            )
            return info
        except AppException:
            raise
        except Exception as exc:
            print(f"[schedule.usecase]   ❌ {info_type.value} 조회 실패: {exc}")
            logger.exception("[schedule] %s 조회 실패: %s", info_type.value, exc)
            raise AppException(
                status_code=502,
                message=(
                    f"외부 데이터 소스에서 {info_type.display_name}({info_type.value})"
                    f" 조회에 실패했습니다: {exc}"
                ),
            ) from exc

    @staticmethod
    def _to_item(info: InvestmentInfo) -> InvestmentInfoItem:
        return InvestmentInfoItem(
            info_type=info.info_type.value,
            display_name=info.info_type.display_name,
            symbol=info.symbol,
            value=info.value,
            unit=info.unit,
            retrieved_at=info.retrieved_at,
            source=info.source,
            description=info.description,
        )
