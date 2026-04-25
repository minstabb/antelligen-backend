from enum import Enum


class EventImportance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @classmethod
    def parse(cls, raw: str) -> "EventImportance":
        if not raw:
            return cls.LOW
        key = raw.strip().upper()
        if key in ("HIGH", "H", "상", "높음"):
            return cls.HIGH
        if key in ("MEDIUM", "MID", "M", "중"):
            return cls.MEDIUM
        return cls.LOW
