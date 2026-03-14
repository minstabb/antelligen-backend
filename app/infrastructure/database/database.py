from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.infrastructure.config.settings import get_settings

settings = get_settings()

DATABASE_URL = (
    f"mysql+aiomysql://{settings.mysql_user}:{settings.mysql_password}"
    f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_schema}"
)

engine = create_async_engine(DATABASE_URL, echo=settings.debug)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
