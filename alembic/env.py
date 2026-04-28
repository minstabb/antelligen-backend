import asyncio
from logging.config import fileConfig
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool, create_engine

from alembic import context

from app.infrastructure.config.settings import get_settings
from app.infrastructure.database.database import Base
from app.infrastructure.database.vector_database import VectorBase
import app.domains.history_agent.infrastructure.orm.event_enrichment_orm  # noqa: F401
import app.domains.sentiment.infrastructure.orm.sns_post_orm  # noqa: F401

# Alembic Config 객체
config = context.config

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate를 위해 Base.metadata + VectorBase.metadata 연결
target_metadata = [Base.metadata, VectorBase.metadata]

# 환경 변수에서 DB URL 구성
settings = get_settings()

# alembic 마이그레이션 전용 sync URL (psycopg2)
SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{quote_plus(settings.postgres_user)}:{quote_plus(settings.postgres_password)}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)

# 앱 런타임 async URL (asyncpg)
DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(settings.postgres_user)}:{quote_plus(settings.postgres_password)}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)


def run_migrations_offline() -> None:
    """오프라인 모드: DB 연결 없이 SQL 스크립트 출력."""
    context.configure(
        url=SYNC_DATABASE_URL,
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


def run_migrations_online() -> None:
    """온라인 모드: sync 엔진으로 마이그레이션 적용 (alembic 전용)."""
    sync_engine = create_engine(SYNC_DATABASE_URL, poolclass=pool.NullPool)
    with sync_engine.connect() as conn:
        do_run_migrations(conn)
    sync_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
