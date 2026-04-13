import json
import math
import os
import time
from typing import Any, TypedDict

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph

from app.common.exception.app_exception import AppException
from app.domains.agent.application.port.finance_agent_provider import (
    FinanceAgentProvider,
)
from app.domains.agent.application.response.investment_signal_response import (
    InvestmentSignalResponse,
)
from app.domains.agent.application.response.sub_agent_response import SubAgentResponse
from app.domains.stock.application.response.stock_collection_response import (
    StockCollectionResponse,
)

_SYSTEM_PROMPT = """당신은 한국 주식 시장 재무 분석 전문가입니다. RAG 파이프라인 내에서 동작합니다.
사용자 질문, 구조화된 주식 데이터, 검색된 문서 청크를 바탕으로 심층 재무 분석을 수행합니다.

분석 지침:
1. 제공된 재무수치(ROE, ROA, 부채비율, 매출, 영업이익, 당기순이익 등)를 반드시 구체적으로 언급하세요.
2. 재무비율 해석 기준을 참고하세요:
   - ROE 15%↑ 우량 / 5%↓ 부진
   - 부채비율 200%↓ 안정 / 300%↑ 위험
   - 영업이익률 10%↑ 양호
   - 매출·영업이익 전년 대비 성장 여부를 반드시 언급하세요.
3. 검색된 문서 청크에 추가 근거가 있으면 반드시 인용하세요.
4. 데이터가 부족하면 보수적으로 neutral을 유지하세요.
5. key_points는 3~5개이며, 각각 수치 또는 사실 근거를 포함해야 합니다.

반드시 아래 JSON 형식으로만 응답하세요 (마크다운, 기타 텍스트 절대 금지):
{
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0~1.0>,
  "summary": "<구체적 수치 포함 한국어 2문장 종합 의견>",
  "key_points": ["<수치/근거 포함 포인트1>", "<포인트2>", "<포인트3>", "<포인트4 선택>", "<포인트5 선택>"]
}"""


class FinanceRagState(TypedDict, total=False):
    user_query: str
    stock_data: StockCollectionResponse
    retrieved_chunks: list[dict[str, Any]]
    llm_payload: dict[str, Any]


class LangGraphFinanceAgentProvider(FinanceAgentProvider):
    def __init__(
        self,
        *,
        api_key: str,
        chat_model: str,
        embedding_model: str,
        top_k: int = 3,
        langsmith_tracing: bool = False,
        langsmith_api_key: str = "",
        langsmith_project: str = "antelligen-backend",
        langsmith_endpoint: str = "https://api.smith.langchain.com",
    ):
        self._configure_langsmith(
            tracing=langsmith_tracing,
            api_key=langsmith_api_key,
            project=langsmith_project,
            endpoint=langsmith_endpoint,
        )
        self._embeddings = OpenAIEmbeddings(
            api_key=api_key,
            model=embedding_model,
        )
        self._llm = ChatOpenAI(
            api_key=api_key,
            model=chat_model,
        )
        self._top_k = top_k
        self._graph = self._build_graph()

    async def analyze(
        self,
        *,
        user_query: str,
        stock_data: StockCollectionResponse,
    ) -> SubAgentResponse:
        started_at = time.perf_counter()

        try:
            state = await self._graph.ainvoke(
                {
                    "user_query": user_query,
                    "stock_data": stock_data,
                }
            )
            payload = state["llm_payload"]
        except json.JSONDecodeError as exc:
            raise AppException(
                status_code=502,
                message="재무분석 RAG 응답을 파싱할 수 없습니다.",
            ) from exc
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                status_code=502,
                message=f"LangGraph 재무분석 중 오류가 발생했습니다: {str(exc)}",
            ) from exc

        execution_time_ms = int((time.perf_counter() - started_at) * 1000)
        signal = InvestmentSignalResponse(
            agent_name="finance",
            ticker=stock_data.ticker,
            signal=payload["signal"],
            confidence=float(payload["confidence"]),
            summary=payload["summary"],
            key_points=payload["key_points"],
        )

        return SubAgentResponse.success_with_signal(
            signal=signal,
            data=self._build_result_data(stock_data, state["retrieved_chunks"]),
            execution_time_ms=execution_time_ms,
        )

    def _build_graph(self):
        graph = StateGraph(FinanceRagState)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("generate", self._generate)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "generate")
        graph.add_edge("generate", END)
        return graph.compile()

    async def _retrieve(self, state: FinanceRagState) -> FinanceRagState:
        stock_data = state["stock_data"]
        chunks = stock_data.document_chunks
        if not chunks:
            return {
                "retrieved_chunks": [],
            }

        query_vector = await self._embeddings.aembed_query(state["user_query"])
        scored_chunks: list[dict[str, Any]] = []

        for chunk in chunks:
            if not chunk.embedding_vector:
                continue
            score = self._cosine_similarity(query_vector, chunk.embedding_vector)
            scored_chunks.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "score": score,
                }
            )

        scored_chunks.sort(key=lambda item: item["score"], reverse=True)
        return {
            "retrieved_chunks": scored_chunks[: self._top_k],
        }

    async def _generate(self, state: FinanceRagState) -> FinanceRagState:
        stock_data = state["stock_data"]
        financial_info = (
            stock_data.financial_information.model_dump(mode="json")
            if stock_data.financial_information
            else {}
        )
        dart_ratios = (
            stock_data.dart_financial_ratios.model_dump(mode="json")
            if stock_data.dart_financial_ratios
            else {}
        )
        retrieved_chunks = state.get("retrieved_chunks", [])

        prompt = json.dumps(
            {
                "user_query": state["user_query"],
                "stock": {
                    "ticker": stock_data.ticker,
                    "stock_name": stock_data.stock_name,
                    "market": stock_data.market,
                    "financial_information": financial_info,
                    "dart_financial_ratios": dart_ratios,
                    "reference_url": stock_data.metadata.reference_url,
                    "collected_at": stock_data.metadata.collected_at.isoformat(),
                },
                "retrieved_chunks": retrieved_chunks,
            },
            ensure_ascii=False,
        )

        response = await self._llm.ainvoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", prompt),
            ]
        )

        return {
            "llm_payload": json.loads(response.content),
        }

    def _build_result_data(
        self,
        stock_data: StockCollectionResponse,
        retrieved_chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        financial_info = stock_data.financial_information
        dart_ratios = stock_data.dart_financial_ratios

        return {
            "ticker": stock_data.ticker,
            "stock_name": stock_data.stock_name,
            "market": stock_data.market,
            "current_price": financial_info.current_price if financial_info else None,
            "currency": financial_info.currency if financial_info else None,
            "market_cap": financial_info.market_cap if financial_info else None,
            "pe_ratio": financial_info.pe_ratio if financial_info else None,
            "dividend_yield": financial_info.dividend_yield if financial_info else None,
            "roe": dart_ratios.roe if dart_ratios else None,
            "roa": dart_ratios.roa if dart_ratios else None,
            "debt_ratio": dart_ratios.debt_ratio if dart_ratios else None,
            "fiscal_year": dart_ratios.fiscal_year if dart_ratios else None,
            "sales": dart_ratios.sales if dart_ratios else None,
            "operating_income": dart_ratios.operating_income if dart_ratios else None,
            "net_income": dart_ratios.net_income if dart_ratios else None,
            "reference_url": stock_data.metadata.reference_url,
            "collected_at": stock_data.metadata.collected_at.isoformat(),
            "retrieved_chunk_count": len(retrieved_chunks),
            "retrieved_chunks": retrieved_chunks,
        }

    def _cosine_similarity(
        self,
        left: list[float],
        right: list[float],
    ) -> float:
        if not left or not right or len(left) != len(right):
            return -1.0

        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return -1.0
        return numerator / (left_norm * right_norm)

    def _configure_langsmith(
        self,
        *,
        tracing: bool,
        api_key: str,
        project: str,
        endpoint: str,
    ) -> None:
        if not tracing:
            return

        os.environ["LANGSMITH_TRACING"] = "true"

        if api_key:
            os.environ["LANGSMITH_API_KEY"] = api_key

        if project:
            os.environ["LANGSMITH_PROJECT"] = project

        if endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = endpoint
