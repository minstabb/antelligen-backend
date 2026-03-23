from abc import ABC, abstractmethod


class StockEmbeddingGenerator(ABC):
    @abstractmethod
    def generate(self, text: str) -> list[float]:
        pass
