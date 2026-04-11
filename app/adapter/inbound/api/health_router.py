from fastapi import APIRouter

from app.infrastructure.config.settings import get_settings
from app.infrastructure.external.serp_client import SerpClient, SerpApiException

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/serp")
async def check_serp_health():
    """SERP API 연결 가용성 스모크 체크"""
    settings = get_settings()

    try:
        client = SerpClient(api_key=settings.serp_api_key)
    except SerpApiException as e:
        return {"status": "error", "message": str(e)}

    ok = await client.ping()
    if ok:
        return {"status": "ok", "message": "SERP API 연결 정상"}
    return {"status": "error", "message": "SERP API 응답 없음"}
