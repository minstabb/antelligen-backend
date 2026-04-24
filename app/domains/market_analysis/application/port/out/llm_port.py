from abc import ABC, abstractmethod


class LLMPort(ABC):
    @abstractmethod
    async def generate_answer(self, question: str, context: str) -> str:
        pass
