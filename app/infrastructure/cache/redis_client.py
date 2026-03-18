import redis.asyncio as aioredis

from app.infrastructure.config.settings import get_settings

settings = get_settings()

redis_client = aioredis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    password=settings.redis_password,
    decode_responses=True,
)


async def get_redis() -> aioredis.Redis:
    return redis_client
