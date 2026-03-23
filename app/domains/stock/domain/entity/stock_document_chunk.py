class StockDocumentChunk:
    def __init__(
        self,
        chunk_id: str,
        chunk_index: int,
        content: str,
        start_char: int,
        end_char: int,
        embedding_vector: list[float] | None = None,
    ):
        self.chunk_id = chunk_id
        self.chunk_index = chunk_index
        self.content = content
        self.start_char = start_char
        self.end_char = end_char
        self.embedding_vector = embedding_vector
