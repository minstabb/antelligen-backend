from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class CuratedMacroEvent:
    date: date
    event_type: str
    region: str
    title: str
    detail: str
    tags: List[str] = field(default_factory=list)
    importance_score: float = 1.0
    source_url: Optional[str] = None
