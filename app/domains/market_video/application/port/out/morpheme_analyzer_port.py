from abc import ABC, abstractmethod


class MorphemeAnalyzerPort(ABC):
    @abstractmethod
    def extract_nouns(self, text: str) -> list[str]:
        pass
