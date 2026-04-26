from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EventImpactMetricOrm(Base):
    __tablename__ = "event_impact_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    detail_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    benchmark_ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    pre_days: Mapped[int] = mapped_column(Integer, nullable=False)
    post_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    cumulative_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    abnormal_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_completeness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bars_data_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "event_date",
            "event_type",
            "detail_hash",
            "pre_days",
            "post_days",
            name="uq_event_impact_metrics_key",
        ),
        Index(
            "ix_event_impact_metrics_event_lookup",
            "ticker",
            "event_date",
            "event_type",
            "detail_hash",
        ),
        Index(
            "ix_event_impact_metrics_event_date",
            "event_date",
        ),
    )
