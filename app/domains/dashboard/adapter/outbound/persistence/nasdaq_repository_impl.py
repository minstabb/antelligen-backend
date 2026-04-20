import logging
from datetime import date
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.dashboard.application.port.out.nasdaq_repository_port import NasdaqRepositoryPort
from app.domains.dashboard.domain.entity.nasdaq_bar import NasdaqBar
from app.domains.dashboard.infrastructure.mapper.nasdaq_bar_mapper import NasdaqBarMapper
from app.domains.dashboard.infrastructure.orm.nasdaq_bar_orm import NasdaqBarOrm

logger = logging.getLogger(__name__)


class NasdaqRepositoryImpl(NasdaqRepositoryPort):

    def __init__(self, db: AsyncSession):
        self._db = db

    async def find_latest_bar_date(self) -> Optional[date]:
        stmt = select(func.max(NasdaqBarOrm.bar_date))
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_bulk(self, bars: List[NasdaqBar]) -> int:
        if not bars:
            return 0

        # asyncpg 파라미터 한계(32767)를 넘지 않도록 청크 단위로 분할
        # 컬럼 6개 기준 최대 5000행씩 처리
        CHUNK_SIZE = 5000
        total = 0

        for i in range(0, len(bars), CHUNK_SIZE):
            chunk = bars[i : i + CHUNK_SIZE]
            values = [
                {
                    "bar_date": bar.bar_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": int(bar.volume),
                }
                for bar in chunk
            ]

            insert_stmt = pg_insert(NasdaqBarOrm).values(values)
            upsert_stmt = (
                insert_stmt.on_conflict_do_update(
                    index_elements=["bar_date"],
                    set_={
                        "open": insert_stmt.excluded.open,
                        "high": insert_stmt.excluded.high,
                        "low": insert_stmt.excluded.low,
                        "close": insert_stmt.excluded.close,
                        "volume": insert_stmt.excluded.volume,
                    },
                )
                .returning(NasdaqBarOrm.id)
            )

            result = await self._db.execute(upsert_stmt)
            total += len(result.fetchall())

        await self._db.commit()
        logger.info("[NasdaqRepository] upsert 완료: %d rows", total)
        return total

    async def find_by_date_range(self, start: date, end: date) -> List[NasdaqBar]:
        stmt = (
            select(NasdaqBarOrm)
            .where(NasdaqBarOrm.bar_date >= start, NasdaqBarOrm.bar_date <= end)
            .order_by(NasdaqBarOrm.bar_date.asc())
        )
        result = await self._db.execute(stmt)
        return [NasdaqBarMapper.to_entity(orm) for orm in result.scalars().all()]
