from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapter.inbound.api.v1_router import api_v1_router
from app.domains.authentication.adapter.inbound.api.authentication_router import router as authentication_router
from app.common.exception.global_exception_handler import register_exception_handlers
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.database.database import Base, engine
from app.infrastructure.database.vector_database import VectorBase, vector_engine

import app.domains.account.infrastructure.orm.account_orm  # noqa: F401
import app.domains.news.infrastructure.orm.saved_article_orm  # noqa: F401
import app.domains.post.infrastructure.orm.post_orm  # noqa: F401
import app.domains.stock.infrastructure.orm.stock_vector_document_orm  # noqa: F401

settings: Settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with vector_engine.begin() as conn:
        await conn.run_sync(VectorBase.metadata.create_all)

    yield


app = FastAPI(debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allowed_frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)
app.include_router(authentication_router)  # /authentication/me (프론트 직접 호출)
register_exception_handlers(app)


@app.get("/")
async def root():
    return {"message": "Hello World"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=33333)
