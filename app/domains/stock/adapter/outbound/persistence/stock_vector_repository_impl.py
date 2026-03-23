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
