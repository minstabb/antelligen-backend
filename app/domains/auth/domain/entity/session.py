from dataclasses import dataclass


@dataclass
class Session:
    user_id: str
    role: str
    token: str
    ttl_seconds: int
