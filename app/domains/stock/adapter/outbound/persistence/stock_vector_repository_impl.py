from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.domains.stock.application.port.stock_vector_repository import (
    StockVectorRepository,
)
from app.domains.stock.domain.entity.stock_vector_document import StockVectorDocument
from app.domains.stock.domain.entity.stock_vector_store_result import (
    StockVectorStoreResult,
)
from app.domains.stock.infrastructure.orm.stock_vector_document_orm import (
    StockVectorDocumentOrm,
)
from app.infrastructure.database.vector_database import VectorAsyncSessionLocal


class StockVectorRepositoryImpl(StockVectorRepository):
    async def save_documents(
        self,
        documents: list[StockVectorDocument],
    ) -> StockVectorStoreResult:
        if not documents:
            return StockVectorStoreResult(
                total_chunk_count=0,
                stored_chunk_count=0,
                skipped_chunk_count=0,
            )

        values = [
            {
                "chunk_id": document.chunk_id,
                "entity_id": document.entity_id,
                "source": document.source,
                "dedup_key": document.dedup_key,
                "chunk_index": document.chunk_index,
                "content": document.content,
                "embedding_vector": document.embedding_vector,
                "collected_at": document.collected_at,
            }
            for document in documents
        ]

        stmt = (
            insert(StockVectorDocumentOrm)
            .values(values)
            .on_conflict_do_nothing(constraint="uq_stock_vector_dedup_chunk")
            .returning(StockVectorDocumentOrm.id)
        )

        async with VectorAsyncSessionLocal() as session:
            result = await session.execute(stmt)
            await session.commit()
            stored_ids = result.scalars().all()

        stored_chunk_count = len(stored_ids)
        total_chunk_count = len(documents)

        return StockVectorStoreResult(
            total_chunk_count=total_chunk_count,
            stored_chunk_count=stored_chunk_count,
            skipped_chunk_count=total_chunk_count - stored_chunk_count,
        )

    async def find_by_entity_id(
        self,
        entity_id: str,
    ) -> Optional[list[StockVectorDocument]]:
        """entity_id(ticker)로 저장된 문서를 조회합니다. 가장 최신 dedup_key 기준."""
        async with VectorAsyncSessionLocal() as session:
            # 가장 최신 collected_at 기준으로 조회
            stmt = (
                select(StockVectorDocumentOrm)
                .where(StockVectorDocumentOrm.entity_id == entity_id)
                .order_by(
                    StockVectorDocumentOrm.collected_at.desc(),
                    StockVectorDocumentOrm.chunk_index.asc(),
                )
            )
            result = await session.execute(stmt)
            orms = result.scalars().all()

            if not orms:
                return None

            # 가장 최신 dedup_key만 필터링
            latest_dedup_key = orms[0].dedup_key
            filtered_orms = [orm for orm in orms if orm.dedup_key == latest_dedup_key]

            return [
                StockVectorDocument(
                    chunk_id=orm.chunk_id,
                    entity_id=orm.entity_id,
                    source=orm.source,
                    dedup_key=orm.dedup_key,
                    chunk_index=orm.chunk_index,
                    content=orm.content,
                    embedding_vector=list(orm.embedding_vector),
                    collected_at=orm.collected_at,
                )
                for orm in filtered_orms
            ]
