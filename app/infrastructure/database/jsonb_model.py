from sqlalchemy import Integer, DateTime, func
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped
from datetime import datetime


class JsonbBase(DeclarativeBase):
    """JSONB 컬럼을 포함한 비정형 데이터 저장용 ORM 베이스."""
    pass


class UnstructuredMixin:
    """
    JSONB 기반 비정형 데이터 공통 컬럼 Mixin.

    사용 예시:
        class MyModel(UnstructuredMixin, JsonbBase):
            __tablename__ = "my_table"
            data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    """
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
