import json
from typing import Optional

import redis.asyncio as aioredis

from app.domains.auth.application.port.out.session_store_port import SessionStorePort
from app.domains.auth.domain.entity.session import Session

SESSION_KEY_PREFIX = "session:"


class RedisSessionRepository(SessionStorePort):
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    async def save(self, session: Session) -> None:
        data = json.dumps({
            "user_id": session.user_id,
            "role": session.role,
            "token": session.token,
        })
        await self._redis.setex(
            f"{SESSION_KEY_PREFIX}{session.token}",
            session.ttl_seconds,
            data,
        )

    async def find_by_token(self, token: str) -> Optional[Session]:
        raw = await self._redis.get(f"{SESSION_KEY_PREFIX}{token}")
        if not raw:
            return None
        parsed = json.loads(raw)
        return Session(
            user_id=parsed["user_id"],
            role=parsed["role"],
            token=parsed["token"],
            ttl_seconds=0,
        )

    async def delete(self, token: str) -> None:
        await self._redis.delete(f"{SESSION_KEY_PREFIX}{token}")
