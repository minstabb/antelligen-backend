import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException

from app.common.response.base_response import BaseResponse
from app.domains.auth.adapter.outbound.in_memory.redis_session_repository import RedisSessionRepository
from app.domains.auth.application.request.login_request import LoginRequest
from app.domains.auth.application.usecase.get_session_usecase import GetSessionUseCase
from app.domains.auth.application.usecase.login_usecase import LoginUseCase
from app.domains.auth.application.usecase.logout_usecase import LogoutUseCase
from app.infrastructure.cache.redis_client import get_redis
from app.infrastructure.config.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

settings = get_settings()


@router.post("/login")
async def login(
    request: LoginRequest,
    redis: aioredis.Redis = Depends(get_redis),
):
    repo = RedisSessionRepository(redis)
    usecase = LoginUseCase(repo, settings.auth_password, settings.session_ttl_seconds)
    try:
        response = await usecase.execute(request)
        return BaseResponse.ok(data=response, message="로그인 성공")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/session/{token}")
async def get_session(
    token: str,
    redis: aioredis.Redis = Depends(get_redis),
):
    repo = RedisSessionRepository(redis)
    usecase = GetSessionUseCase(repo)
    session = await usecase.execute(token)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return BaseResponse.ok(data=session)


@router.delete("/logout/{token}")
async def logout(
    token: str,
    redis: aioredis.Redis = Depends(get_redis),
):
    repo = RedisSessionRepository(redis)
    usecase = LogoutUseCase(repo)
    await usecase.execute(token)
    return BaseResponse.ok(message="로그아웃 성공")
