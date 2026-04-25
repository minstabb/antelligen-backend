from datetime import date
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.disclosure.application.port.disclosure_repository_port import DisclosureRepositoryPort
from app.domains.disclosure.domain.entity.disclosure import Disclosure
from app.domains.disclosure.infrastructure.mapper.disclosure_mapper import DisclosureMapper
from app.domains.disclosure.infrastructure.orm.disclosure_orm import DisclosureOrm


class DisclosureRepositoryImpl(DisclosureRepositoryPort):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def upsert_bulk(self, disclosures: list[Disclosure]) -> int:
        if not disclosures:
            return 0

        values = [
            {
                "rcept_no": d.rcept_no,
                "corp_code": d.corp_code,
                "report_nm": d.report_nm,
                "rcept_dt": d.rcept_dt,
                "pblntf_ty": d.pblntf_ty,
                "pblntf_detail_ty": d.pblntf_detail_ty,
                "rm": d.rm,
                "disclosure_group": d.disclosure_group,
                "source_mode": d.source_mode,
                "is_core": d.is_core,
            }
            for d in disclosures
        ]

        stmt = (
            insert(DisclosureOrm)
            .values(values)
            .on_conflict_do_update(
                index_elements=["rcept_no"],
                set_={
                    "corp_code": insert(DisclosureOrm).excluded.corp_code,
                    "report_nm": insert(DisclosureOrm).excluded.report_nm,
                    "rcept_dt": insert(DisclosureOrm).excluded.rcept_dt,
                    "pblntf_ty": insert(DisclosureOrm).excluded.pblntf_ty,
                    "pblntf_detail_ty": insert(DisclosureOrm).excluded.pblntf_detail_ty,
                    "rm": insert(DisclosureOrm).excluded.rm,
                    "disclosure_group": insert(DisclosureOrm).excluded.disclosure_group,
                    "source_mode": insert(DisclosureOrm).excluded.source_mode,
                    "is_core": insert(DisclosureOrm).excluded.is_core,
                },
            )
            .returning(DisclosureOrm.id)
        )

        result = await self._db.execute(stmt)
        await self._db.commit()
        return len(result.fetchall())

    async def find_by_rcept_no(self, rcept_no: str) -> Optional[Disclosure]:
        stmt = select(DisclosureOrm).where(DisclosureOrm.rcept_no == rcept_no)
        result = await self._db.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return DisclosureMapper.to_entity(orm)

    async def find_by_corp_code(self, corp_code: str, limit: int = 50) -> list[Disclosure]:
        stmt = (
            select(DisclosureOrm)
            .where(DisclosureOrm.corp_code == corp_code)
            .order_by(DisclosureOrm.rcept_dt.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [DisclosureMapper.to_entity(orm) for orm in result.scalars().all()]

    async def find_latest_rcept_dt(self) -> Optional[date]:
        stmt = select(func.max(DisclosureOrm.rcept_dt))
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def exists_by_rcept_no(self, rcept_no: str) -> bool:
        stmt = select(func.count()).select_from(DisclosureOrm).where(
            DisclosureOrm.rcept_no == rcept_no
        )
        result = await self._db.execute(stmt)
        return result.scalar_one() > 0

    async def find_unprocessed_core(self, limit: int = 50) -> list[Disclosure]:
        from app.domains.disclosure.infrastructure.orm.disclosure_document_orm import (
            DisclosureDocumentOrm,
        )
        # 핵심 공시 중 disclosure_documents에 아직 레코드가 없는 것
        already_processed = (
            select(DisclosureDocumentOrm.rcept_no)
            .where(DisclosureDocumentOrm.summary_text.isnot(None))
        )
        stmt = (
            select(DisclosureOrm)
            .where(
                DisclosureOrm.is_core.is_(True),
                ~DisclosureOrm.rcept_no.in_(already_processed),
            )
            .order_by(DisclosureOrm.rcept_dt.desc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [DisclosureMapper.to_entity(orm) for orm in result.scalars().all()]
