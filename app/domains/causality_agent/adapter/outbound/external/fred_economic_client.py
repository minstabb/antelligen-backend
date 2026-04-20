import logging
from datetime import date
from typing import Any, Dict, List

import httpx

from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_SERIES = ["FEDFUNDS", "CPIAUCSL", "UNRATE"]


class FredEconomicClient:
    """FRED API 경제 시계열 클라이언트 (날짜 범위 기반)."""

    async def fetch_series(
        self,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        api_key = get_settings().fred_api_key
        results = []
        async with httpx.AsyncClient(timeout=15) as client:
            for series_id in _SERIES:
                observations = await self._fetch_one(
                    client, api_key, series_id, start_date, end_date
                )
                results.append({"series_id": series_id, "observations": observations})
        return results

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        params = {
            "series_id": series_id,
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
            "api_key": api_key,
            "file_type": "json",
        }
        try:
            resp = await client.get(_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [
                {"date": obs["date"], "value": obs["value"]}
                for obs in data.get("observations", [])
                if obs["value"] != "."
            ]
        except Exception as exc:
            logger.warning("[FRED] %s 조회 실패: %s", series_id, exc)
            return []
