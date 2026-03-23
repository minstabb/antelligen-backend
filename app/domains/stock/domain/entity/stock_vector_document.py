from datetime import datetime


class StockVectorDocument:
    def __init__(
        self,
        chunk_id: str,
        entity_id: str,
        source: str,
        dedup_key: str,
        chunk_index: int,
        content: str,
        embedding_vector: list[float],
        collected_at: datetime,
    ):
        self.chunk_id = chunk_id
        self.entity_id = entity_id
        self.source = source
        self.dedup_key = dedup_key
        self.chunk_index = chunk_index
        self.content = content
        self.embedding_vector = embedding_vector
        self.collected_at = collected_at
