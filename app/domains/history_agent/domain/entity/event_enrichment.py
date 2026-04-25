import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def compute_detail_hash(detail: str, constituent_ticker: Optional[str] = None) -> str:
    """detail_hash 산정. constituent_ticker가 주어지면 prefix로 포함해

    같은 ETF 내 서로 다른 보유 종목의 동일한 공시 텍스트가 충돌하지 않도록 한다.
    """
    material = f"{constituent_ticker}|{detail}" if constituent_ticker else detail
    return hashlib.sha256(material.encode()).hexdigest()[:16]


@dataclass
class EventEnrichment:
    ticker: str
    event_date: date
    event_type: str
    detail_hash: str
    title: str
    causality: Optional[List[Dict[str, Any]]] = field(default=None)
    importance_score: Optional[float] = field(default=None)
    id: Optional[int] = field(default=None)
    created_at: Optional[datetime] = field(default=None)
    updated_at: Optional[datetime] = field(default=None)
