import logging
from datetime import date
from typing import List

import httpx

from app.domains.dashboard.application.port.out.fred_macro_port import FredMacroPort
from app.domains.dashboard.domain.entity.macro_data_point import MacroDataPoint
from app.domains.dashboard.domain.exception.fred_exception import FredApiException
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def _months_ago(n: int) -> date:
    today = date.today()
    month = today.month - n
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _parse_observations(data: dict, series_id: str) -> List[MacroDataPoint]:
    observations = data.get("observations", [])
    points: List[MacroDataPoint] = []
    for obs in observations:
        value_str = obs.get("value", ".")
        if value_str == ".":
            continue
        try:
            points.append(
                MacroDataPoint(
                    date=date.fromisoformat(obs["date"]),
                    value=float(value_str),
                )
            )
        except (ValueError, KeyError) as e:
            logger.warning("[FRED] 행 파싱 실패 (series=%s, obs=%s): %s", series_id, obs, e)
    return points


class FredMacroClient(FredMacroPort):

    async def fetch_series(self, series_id: str, months: int) -> List[MacroDataPoint]:
        observation_start = _months_ago(months).strftime("%Y-%m-%d")
        params = {
            "series_id": series_id,
            "api_key": get_settings().fred_api_key,
            "observation_start": observation_start,
            "file_type": "json",
            "sort_order": "asc",
        }

        logger.info("[FRED] 조회 시작 (series=%s, start=%s)", series_id, observation_start)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(FRED_BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

            points = _parse_observations(data, series_id)
            logger.info("[FRED] 조회 완료 (series=%s, count=%d)", series_id, len(points))
            return points

        except FredApiException:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("[FRED] HTTP 오류 (series=%s): %s", series_id, e)
            raise FredApiException(
                f"FRED API HTTP 오류 (series={series_id}): {e.response.status_code}"
            )
        except httpx.TimeoutException:
            logger.error("[FRED] 타임아웃 (series=%s)", series_id)
            raise FredApiException(f"FRED API 타임아웃 (series={series_id})")
        except Exception as e:
            logger.error("[FRED] 예상치 못한 오류 (series=%s): %s", series_id, e)
            raise FredApiException(f"FRED API 호출 실패 (series={series_id}): {e}")
