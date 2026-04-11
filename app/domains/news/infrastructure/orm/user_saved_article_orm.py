from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.database import Base


class UserSavedArticleOrm(Base):
    """사용자별 관심 기사 메타데이터 (구조화 데이터 / MySQL 역할)"""

    __tablename__ = "user_saved_article"
    __table_args__ = (
        UniqueConstraint("account_id", "link_hash", name="uq_user_saved_article_account_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    link_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
