from datetime import datetime

from sqlalchemy import Integer, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.vector_database import VectorBase


class ArticleContentOrm(VectorBase):
    """기사 본문 및 비정형 원본 데이터 (PostgreSQL JSONB)"""

    __tablename__ = "interest_article_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_saved_article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
