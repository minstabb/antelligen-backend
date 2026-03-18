# /api/v1 공통 라우터 집합
# 팀원 가이드: 새 도메인 라우터를 만들면 이 파일에 include_router만 추가하면 된다.
#
# 추가 예시:
#   from app.domains.news.adapter.inbound.api.news_router import router as news_router
#   api_v1_router.include_router(news_router)

from fastapi import APIRouter

from app.domains.agent.adapter.inbound.api.agent_router import router as agent_router
from app.domains.auth.adapter.inbound.api.auth_router import router as auth_router
from app.domains.kakao_auth.adapter.inbound.api.kakao_auth_router import router as kakao_auth_router
from app.domains.api_schema.adapter.inbound.api.api_schema_router import router as api_schema_router
from app.domains.news.adapter.inbound.api.news_router import router as news_router
from app.domains.post.adapter.inbound.api.post_router import router as post_router
from app.domains.stock.adapter.inbound.api.stock_router import router as stock_router

# 모든 API는 /api/v1 prefix를 가진다.
api_v1_router = APIRouter(prefix="/api/v1")

# --- 도메인 라우터 등록 ---
api_v1_router.include_router(post_router)       # POST: /api/v1/post/...
api_v1_router.include_router(stock_router)      # STOCK: /api/v1/stock/...
api_v1_router.include_router(agent_router)       # AGENT: /api/v1/agent/...
api_v1_router.include_router(api_schema_router)  # AGENT SCHEMA: /api/v1/agent-schema
api_v1_router.include_router(news_router)        # NEWS: /api/v1/news/...
api_v1_router.include_router(auth_router)        # AUTH: /api/v1/auth/...
api_v1_router.include_router(kakao_auth_router)  # KAKAO AUTH: /api/v1/kakao-authentication/...
# api_v1_router.include_router(finance_router)  # 재무 에이전트
# api_v1_router.include_router(disclosure_router)  # 공시 에이전트
