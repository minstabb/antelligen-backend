from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.infrastructure.config.settings import get_settings

settings = get_settings()

VECTOR_DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(settings.postgres_user)}:{quote_plus(settings.postgres_password)}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)

vector_engine = create_async_engine(VECTOR_DATABASE_URL, echo=settings.debug)

VectorAsyncSessionLocal = async_sessionmaker(
    vector_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class VectorBase(DeclarativeBase):
    pass


async def get_vector_db() -> AsyncSession:
    async with VectorAsyncSessionLocal() as session:
        yield session
