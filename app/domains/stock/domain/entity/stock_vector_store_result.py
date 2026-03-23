class StockVectorStoreResult:
    def __init__(
        self,
        total_chunk_count: int,
        stored_chunk_count: int,
        skipped_chunk_count: int,
    ):
        self.total_chunk_count = total_chunk_count
        self.stored_chunk_count = stored_chunk_count
        self.skipped_chunk_count = skipped_chunk_count

    @property
    def duplicate_prevented(self) -> bool:
        return self.skipped_chunk_count > 0
