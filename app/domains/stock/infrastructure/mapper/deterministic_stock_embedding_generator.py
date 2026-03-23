import hashlib

from app.domains.stock.application.port.stock_embedding_generator import (
    StockEmbeddingGenerator,
)


class DeterministicStockEmbeddingGenerator(StockEmbeddingGenerator):
    def __init__(self, dimensions: int = 16):
        self._dimensions = dimensions

    def generate(self, text: str) -> list[float]:
        normalized_text = " ".join(text.split()).lower()
        if not normalized_text:
            return [0.0] * self._dimensions

        digest = hashlib.sha256(normalized_text.encode("utf-8")).digest()
        vector: list[float] = []

        for index in range(self._dimensions):
            raw_value = digest[index % len(digest)]
            normalized_value = round((raw_value / 127.5) - 1.0, 6)
            vector.append(normalized_value)

        return vector
