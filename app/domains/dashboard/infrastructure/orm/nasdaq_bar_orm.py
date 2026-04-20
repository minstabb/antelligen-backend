from datetime import date

from sqlalchemy import Date, Float, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.database import Base


class NasdaqBarOrm(Base):
    __tablename__ = "nasdaq_bars"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bar_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_nasdaq_bars_bar_date", "bar_date"),
    )
