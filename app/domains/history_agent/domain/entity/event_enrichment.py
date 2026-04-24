import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def compute_detail_hash(detail: str) -> str:
    return hashlib.sha256(detail.encode()).hexdigest()[:16]


@dataclass
class EventEnrichment:
    ticker: str
    event_date: date
    event_type: str
    detail_hash: str
    title: str
    causality: Optional[List[Dict[str, Any]]] = field(default=None)
    id: Optional[int] = field(default=None)
    created_at: Optional[datetime] = field(default=None)
    updated_at: Optional[datetime] = field(default=None)
