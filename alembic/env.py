import asyncio
from logging.config import fileConfig
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool

from alembic import context

from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import Base
import app.domains.history_agent.infrastructure.orm.event_enrichment_orm  # noqa: F401

# Alembic Config 객체
config = context.config

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate를 위해 Base.metadata 연결
target_metadata = Base.metadata

# 환경 변수에서 DB URL 구성
settings = get_settings()
DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(settings.postgres_user)}:{quote_plus(settings.postgres_password)}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)


def run_migrations_offline() -> None:
    """오프라인 모드: DB 연결 없이 SQL 스크립트 출력."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """온라인 모드: async 엔진으로 실제 DB에 마이그레이션 적용."""
    async_engine = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)
    async with async_engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await async_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
