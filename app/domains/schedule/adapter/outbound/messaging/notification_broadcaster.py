"""인-프로세스 SSE 구독자 pub/sub 브로드캐스터.

주의: 단일 프로세스 메모리 기반이므로 uvicorn --workers 가 2 이상이면 워커 간 공유되지 않는다.
규모 확장 시 Redis pub/sub 로 대체하면 된다.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


class NotificationBroadcaster:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(queue)
        print(
            f"[schedule.broadcaster] 구독자 +1 (total={len(self._subscribers)})"
        )
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)
        print(
            f"[schedule.broadcaster] 구독자 -1 (total={len(self._subscribers)})"
        )

    async def publish(self, payload: Dict[str, Any]) -> None:
        async with self._lock:
            subs = list(self._subscribers)
        print(
            f"[schedule.broadcaster] publish 구독자={len(subs)} event_id="
            f"{payload.get('event_id')} success={payload.get('success')}"
        )
        for q in subs:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                print("[schedule.broadcaster] ⚠ 구독자 큐 풀 — 드롭")
                logger.warning("[schedule.broadcaster] subscriber queue full")


_singleton: Optional[NotificationBroadcaster] = None


def get_notification_broadcaster() -> NotificationBroadcaster:
    global _singleton
    if _singleton is None:
        _singleton = NotificationBroadcaster()
    return _singleton
