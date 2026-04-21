from dataclasses import dataclass
from typing import Optional


@dataclass
class ForeignFiling:
    """해외(US) SEC 공시 엔티티 (순수 Python)"""
    ticker: str
    form_type: str          # 8-K, 10-K, 10-Q, …
    filed_date: str         # YYYY-MM-DD
    report_date: str        # 보고 대상 기간
    description: str        # 공시 제목/설명
    url: Optional[str] = None
    accession_number: Optional[str] = None
