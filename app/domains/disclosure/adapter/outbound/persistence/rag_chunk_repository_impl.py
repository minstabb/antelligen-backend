import logging
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.disclosure.application.port.rag_chunk_repository_port import (
    RagChunkRepositoryPort,
)
from app.domains.disclosure.domain.entity.rag_document_chunk import RagDocumentChunk
from app.domains.disclosure.infrastructure.mapper.rag_document_chunk_mapper import (
    RagDocumentChunkMapper,
)
from app.domains.disclosure.infrastructure.orm.rag_document_chunk_orm import (
    RagDocumentChunkOrm,
)

logger = logging.getLogger(__name__)


class RagChunkRepositoryImpl(RagChunkRepositoryPort):

    def __init__(self, db: AsyncSession):
        self._db = db

    async def upsert_bulk(self, chunks: list[RagDocumentChunk]) -> int:
        """청크를 벌크 삽입한다. 중복(rcept_no + chunk_hash)은 무시한다."""
        if not chunks:
            return 0

        inserted_count = 0

        for chunk in chunks:
            values = {
                "rcept_no": chunk.rcept_no,
                "corp_code": chunk.corp_code,
                "disclosure_document_id": chunk.disclosure_document_id,
                "report_nm": chunk.report_nm,
                "document_type": chunk.document_type,
                "section_title": chunk.section_title,
                "chunk_index": chunk.chunk_index,
                "chunk_text": chunk.chunk_text,
                "chunk_hash": chunk.chunk_hash,
                "embedding": chunk.embedding,
                "created_at": chunk.created_at,
                "updated_at": chunk.updated_at,
            }

            stmt = (
                insert(RagDocumentChunkOrm)
                .values(values)
                .on_conflict_do_nothing(
                    constraint="uq_rag_chunks_rcept_chunk",
                )
            )

            result = await self._db.execute(stmt)
            if result.rowcount > 0:
                inserted_count += 1

        await self._db.commit()

        logger.info(
            "RAG 청크 벌크 삽입 완료: 입력=%d, 삽입=%d",
            len(chunks),
            inserted_count,
        )
        return inserted_count

    async def find_by_rcept_no(self, rcept_no: str) -> list[RagDocumentChunk]:
        """접수번호로 청크를 조회한다."""
        stmt = (
            select(RagDocumentChunkOrm)
            .where(RagDocumentChunkOrm.rcept_no == rcept_no)
            .order_by(RagDocumentChunkOrm.chunk_index)
        )
        result = await self._db.execute(stmt)
        return [
            RagDocumentChunkMapper.to_entity(orm) for orm in result.scalars().all()
        ]

    async def find_business_chunks_by_corp_code(
        self,
        corp_code: str,
        limit: int = 5,
    ) -> list[RagDocumentChunk]:
        """사업보고서 본문 중 '사업의 내용' / 매출 구성 관련 청크 우선 반환.

        키워드 매칭 우선순위:
          1. section_title 또는 chunk_text 에 '사업의 내용' 포함
          2. chunk_text 에 '매출' 또는 '매출액' 포함
        """
        keywords = ["사업의 내용", "매출액", "매출"]
        like_clauses = " OR ".join(
            f"chunk_text ILIKE :kw{i} OR COALESCE(section_title, '') ILIKE :kw{i}"
            for i in range(len(keywords))
        )
        # report_document(사업/분기/반기보고서) 우선, 그 외도 fallback 허용
        query = text(f"""
            SELECT id, rcept_no, corp_code, disclosure_document_id, report_nm,
                   document_type, section_title, chunk_index, chunk_text, chunk_hash,
                   embedding, created_at, updated_at
            FROM rag_document_chunks
            WHERE corp_code = :corp_code
              AND ({like_clauses})
            ORDER BY
                CASE WHEN document_type = 'report_document' THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT :limit
        """)
        params: dict = {"corp_code": corp_code, "limit": limit}
        for i, kw in enumerate(keywords):
            params[f"kw{i}"] = f"%{kw}%"

        try:
            result = await self._db.execute(query, params)
            rows = result.fetchall()
        except Exception as e:
            logger.warning("[RAG] business chunks 조회 실패 corp_code=%s: %s", corp_code, e)
            return []

        return [
            RagDocumentChunk(
                chunk_id=row.id,
                rcept_no=row.rcept_no,
                corp_code=row.corp_code,
                disclosure_document_id=row.disclosure_document_id,
                report_nm=row.report_nm,
                document_type=row.document_type,
                section_title=row.section_title,
                chunk_index=row.chunk_index,
                chunk_text=row.chunk_text,
                chunk_hash=row.chunk_hash,
                embedding=list(row.embedding) if row.embedding is not None else None,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        corp_code: Optional[str] = None,
    ) -> list[RagDocumentChunk]:
        """pgvector 코사인 거리(<=>)를 이용한 유사 청크 검색."""
        # pgvector cosine distance operator를 사용
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        filters = ""
        params = {"embedding": embedding_str, "limit": limit}
        if corp_code:
            filters = "WHERE corp_code = :corp_code"
            params["corp_code"] = corp_code

        query = text(f"""
            SELECT id, rcept_no, corp_code, disclosure_document_id, report_nm,
                   document_type, section_title, chunk_index, chunk_text, chunk_hash,
                   embedding, created_at, updated_at
            FROM rag_document_chunks
            {filters}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)

        try:
            async with self._db.begin_nested():
                result = await self._db.execute(query, params)
                rows = result.fetchall()
        except Exception:
            return []

        chunks = []
        for row in rows:
            embedding_val = list(row.embedding) if row.embedding is not None else None
            chunk = RagDocumentChunk(
                chunk_id=row.id,
                rcept_no=row.rcept_no,
                corp_code=row.corp_code,
                disclosure_document_id=row.disclosure_document_id,
                report_nm=row.report_nm,
                document_type=row.document_type,
                section_title=row.section_title,
                chunk_index=row.chunk_index,
                chunk_text=row.chunk_text,
                chunk_hash=row.chunk_hash,
                embedding=embedding_val,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            chunks.append(chunk)

        return chunks
