import io
import logging
from datetime import date
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

# Caldara & Iacoviello GPR Index — monthly CSV (publicly available)
_GPR_CSV_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
_GPR_CSV_FALLBACK = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xlsx"


class GprIndexClient:
    """GPR(Geopolitical Risk) Index CSV/XLS 다운로드 + 날짜 범위 필터."""

    async def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        raw = await self._download()
        if raw is None:
            return []
        return self._parse(raw, start_date, end_date)

    async def _download(self) -> bytes | None:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for url in (_GPR_CSV_URL, _GPR_CSV_FALLBACK):
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.content
                except Exception as exc:
                    logger.warning("[GPR] %s 다운로드 실패: %s", url, exc)
        return None

    def _parse(self, raw: bytes, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        try:
            import pandas as pd

            df = pd.read_excel(io.BytesIO(raw))
            # 첫 번째 컬럼이 날짜, 두 번째 컬럼이 GPR
            date_col = df.columns[0]
            gpr_col = df.columns[1]
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col, gpr_col])

            result = []
            for _, row in df.iterrows():
                row_date = row[date_col].date()
                if row_date < start_date or row_date > end_date:
                    continue
                result.append(
                    {
                        "date": row_date.isoformat(),
                        "gpr": float(row[gpr_col]),
                    }
                )
            return result
        except Exception as exc:
            logger.warning("[GPR] 파싱 실패: %s", exc)
            return []
