from abc import ABC, abstractmethod
from typing import Optional

from app.domains.disclosure.domain.entity.rag_document_chunk import RagDocumentChunk


class RagChunkRepositoryPort(ABC):

    @abstractmethod
    async def upsert_bulk(self, chunks: list[RagDocumentChunk]) -> int:
        pass

    @abstractmethod
    async def find_by_rcept_no(self, rcept_no: str) -> list[RagDocumentChunk]:
        pass

    @abstractmethod
    async def search_similar(
        self,
        embedding: list[float],
        limit: int = 10,
        corp_code: Optional[str] = None,
    ) -> list[RagDocumentChunk]:
        pass

    @abstractmethod
    async def find_business_chunks_by_corp_code(
        self,
        corp_code: str,
        limit: int = 5,
    ) -> list[RagDocumentChunk]:
        """사업보고서 청크 중 '사업의 내용' / 매출 구성 관련 텍스트를 우선 추출한다.

        company_profile 의 사업 개요 / 매출원 요약에 LLM 컨텍스트로 사용된다.
        """
        pass
