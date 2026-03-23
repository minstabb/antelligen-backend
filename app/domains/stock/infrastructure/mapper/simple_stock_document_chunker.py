import hashlib

from app.domains.stock.application.port.stock_document_chunker import (
    StockDocumentChunker,
)
from app.domains.stock.domain.entity.stock_document_chunk import StockDocumentChunk


class SimpleStockDocumentChunker(StockDocumentChunker):
    def __init__(self, max_chunk_length: int = 120):
        self._max_chunk_length = max_chunk_length

    def chunk(
        self,
        *,
        entity_id: str,
        source: str,
        dedup_key: str,
        document_text: str,
    ) -> list[StockDocumentChunk]:
        normalized_lines = [
            line.strip() for line in document_text.splitlines() if line and line.strip()
        ]
        if not normalized_lines:
            return []

        grouped_contents = self._group_lines(normalized_lines)
        chunks: list[StockDocumentChunk] = []
        cursor = 0

        for index, content in enumerate(grouped_contents):
            start_char = document_text.find(content, cursor)
            if start_char < 0:
                start_char = cursor
            end_char = start_char + len(content)
            cursor = end_char

            chunk_id = self._build_chunk_id(
                entity_id=entity_id,
                source=source,
                dedup_key=dedup_key,
                chunk_index=index,
                content=content,
            )
            chunks.append(
                StockDocumentChunk(
                    chunk_id=chunk_id,
                    chunk_index=index,
                    content=content,
                    start_char=start_char,
                    end_char=end_char,
                )
            )

        return chunks

    def _group_lines(self, lines: list[str]) -> list[str]:
        grouped: list[str] = []
        current_lines: list[str] = []
        current_length = 0

        for line in lines:
            additional_length = len(line) if not current_lines else len(line) + 1
            if current_lines and current_length + additional_length > self._max_chunk_length:
                grouped.append("\n".join(current_lines))
                current_lines = [line]
                current_length = len(line)
                continue

            current_lines.append(line)
            current_length += additional_length

        if current_lines:
            grouped.append("\n".join(current_lines))

        return grouped

    def _build_chunk_id(
        self,
        *,
        entity_id: str,
        source: str,
        dedup_key: str,
        chunk_index: int,
        content: str,
    ) -> str:
        chunk_basis = f"{entity_id}|{source}|{dedup_key}|{chunk_index}|{content}"
        return hashlib.sha256(chunk_basis.encode("utf-8")).hexdigest()
