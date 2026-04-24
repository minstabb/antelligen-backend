from abc import ABC, abstractmethod


class LlmChainPort(ABC):
    @abstractmethod
    async def analyze(self, question: str, context: str) -> str:
        pass
