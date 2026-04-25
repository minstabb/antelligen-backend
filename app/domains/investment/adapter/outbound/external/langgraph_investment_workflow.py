"""
LangGraph 기반 투자 판단 멀티 에이전트 워크플로우.

흐름:
    START
      └→ orchestrator ──────────────────────────────────────────────────┐
              ↑           (conditional routing by next_agent)            │
              │      ┌── "retrieval"  → retrieval_agent                  │
              └──────┤── "analysis"   → analysis_agent                   │
                     ├── "synthesis"  → synthesis_agent                  │
                     └── "end"        → END ←──────────────────────────  ┘

Orchestrator 동작 순서:
  1) 첫 호출 시 QueryParser로 사용자 질문을 파싱하여 parsed_query를 State에 기록한다.
  2) State 상태에 따라 다음 에이전트를 동적으로 결정한다.
  3) 최대 반복 횟수(max_iterations)를 초과하면 강제 종료한다.

SOURCE_REGISTRY:
  investment_source_registry.py 에 등록된 키만 실제 호출한다.
  미구현 소스는 조용히 무시하며 확장 포인트 주석으로 표시한다.
"""

import asyncio
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypedDict
from urllib.parse import parse_qs, urlparse

import json

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.investment.adapter.outbound.external.investment_decision_analyzer import (
    InvestmentDecisionAnalyzer,
)
from app.domains.investment.adapter.outbound.external.investment_signal_analyzer import (
    InvestmentSignalAnalyzer,
)
from app.domains.investment.adapter.outbound.external.investment_source_registry import (
    IMPLEMENTED_SOURCE_KEYS,
)
from app.domains.investment.adapter.outbound.external.llm_query_parser import LLMQueryParser
from app.domains.investment.adapter.outbound.persistence.investment_youtube_repository import (
    InvestmentYoutubeRepository,
)
from app.domains.investment.application.port.investment_workflow_port import InvestmentWorkflowPort
from app.domains.investment.domain.value_object.parsed_query import ParsedQuery
from app.domains.market_video.adapter.outbound.external.youtube_comment_client import YoutubeCommentClient
from app.domains.market_video.adapter.outbound.external.youtube_search_client import YoutubeSearchClient
from app.domains.news.adapter.outbound.external.investment_news_collector import InvestmentNewsCollector
from app.domains.news.adapter.outbound.persistence.investment_news_repository import InvestmentNewsRepository

MAX_ITERATIONS = 10

# 영상당 최대 수집 댓글 수 / 댓글을 수집할 최대 영상 수
_MAX_COMMENTS_PER_VIDEO = 5
_MAX_VIDEOS_FOR_COMMENTS = 3

# 소스별 최대 실행 시간 (초) — 초과 시 해당 소스만 실패로 처리
RETRIEVAL_TIMEOUT_SECS = 30


# ──────────────────────────────────────────────
# 공유 State 정의
# ──────────────────────────────────────────────

class InvestmentAgentState(TypedDict, total=False):
    user_id: str
    user_query: str

    # Query Parser 결과 (Orchestrator 첫 호출 시 기록)
    parsed_query: Optional[ParsedQuery]

    # Orchestrator 제어
    next_agent: str       # "retrieval" | "analysis" | "synthesis" | "end"
    iteration_count: int
    max_iterations: int

    # 각 에이전트 결과
    retrieved_data: list[dict[str, Any]]   # Retrieval Agent 결과
    investment_decision: dict[str, Any]    # Rule 기반 투자 판단 (buy/hold/sell)
    analysis_insights: dict[str, Any]      # Analysis Agent 결과
    final_response: str                    # Synthesis Agent 최종 응답


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────

def _parse_youtube_datetime(dt_str: str) -> datetime | None:
    """YouTube API published_at 문자열('2024-01-15T12:34:56Z')을 timezone-aware datetime으로 변환한다."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)


def _extract_video_id(video_url: str) -> str | None:
    """YouTube URL에서 video_id를 추출한다. 파싱 실패 시 None 반환."""
    try:
        params = parse_qs(urlparse(video_url).query)
        ids = params.get("v", [])
        return ids[0] if ids else None
    except Exception:
        return None


# ──────────────────────────────────────────────
# 워크플로우 클래스 (노드는 인스턴스 메서드)
# ──────────────────────────────────────────────

class LangGraphInvestmentWorkflow(InvestmentWorkflowPort):
    """LangGraph 기반 투자 판단 워크플로우 Port 구현체."""

    def __init__(
        self,
        *,
        api_key: str,
        serp_api_key: str = "",
        youtube_api_key: str = "",
        db_session: Optional[AsyncSession] = None,
        query_parser_model: str = "gpt-5-mini",
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self._query_parser = LLMQueryParser(api_key=api_key, model=query_parser_model)
        self._max_iterations = max_iterations
        self._news_collector = InvestmentNewsCollector(serp_api_key=serp_api_key) if serp_api_key else None
        self._youtube_client = YoutubeSearchClient(api_key=youtube_api_key) if youtube_api_key else None
        self._youtube_comment_client = YoutubeCommentClient(api_key=youtube_api_key) if youtube_api_key else None
        self._db_session = db_session
        self._llm = ChatOpenAI(api_key=api_key, model=query_parser_model, temperature=0.3)

        # 소스 핸들러 레지스트리: required_data 키 → async callable(company: str) → list[dict]
        # 새 소스 추가 시 이 dict에만 등록하면 병렬 실행 프레임워크가 자동 적용된다.
        self._source_handlers: dict[str, Callable] = {
            "뉴스": self._fetch_news,
            "유튜브": self._fetch_youtube,
            # 확장 포인트: "종목": self._fetch_stock,
        }

        # 투자 심리 지표 산출기 (유튜브 댓글 감성·키워드 / 뉴스 이벤트 분류)
        self._signal_analyzer = InvestmentSignalAnalyzer(api_key=api_key)

        # 투자 판단 산출기 (deterministic rule + LLM rationale)
        self._decision_analyzer = InvestmentDecisionAnalyzer(api_key=api_key)

        self._graph = self._build_graph()
        print(
            f"[LangGraphInvestmentWorkflow] 그래프 빌드 완료 | max_iterations={max_iterations} | "
            f"뉴스수집={'활성' if self._news_collector else '비활성'} | "
            f"youtube={'활성' if self._youtube_client else '비활성'} | "
            f"db={'연결됨' if self._db_session else '미연결'}"
        )

    # ── 단일 진입점 ───────────────────────────

    async def run(self, *, user_id: str, query: str) -> dict:
        """워크플로우를 실행하고 최종 State를 반환한다."""
        print(f"\n[LangGraphInvestmentWorkflow] run_agent_workflow 진입 "
              f"| user_id={user_id} | query={query!r}")

        initial_state: InvestmentAgentState = {
            "user_id": user_id,
            "user_query": query,
            "iteration_count": 0,
            "max_iterations": self._max_iterations,
        }

        final_state = await self._graph.ainvoke(initial_state)

        print(f"\n[LangGraphInvestmentWorkflow] 워크플로우 종료 "
              f"| total_iterations={final_state.get('iteration_count', 0)}")
        return final_state

    # ── 그래프 빌드 ───────────────────────────

    def _build_graph(self):
        graph = StateGraph(InvestmentAgentState)

        graph.add_node("orchestrator", self._orchestrator_node)
        graph.add_node("retrieval", self._retrieval_node)
        graph.add_node("analysis", self._analysis_node)
        graph.add_node("synthesis", self._synthesis_node)

        graph.add_edge(START, "orchestrator")

        graph.add_conditional_edges(
            "orchestrator",
            self._route_from_orchestrator,
            {
                "retrieval": "retrieval",
                "analysis": "analysis",
                "synthesis": "synthesis",
                "end": END,
            },
        )

        graph.add_edge("retrieval", "orchestrator")
        graph.add_edge("analysis", "orchestrator")
        graph.add_edge("synthesis", "orchestrator")

        return graph.compile()

    # ── 라우팅 함수 ───────────────────────────

    def _route_from_orchestrator(self, state: InvestmentAgentState) -> str:
        next_agent = state.get("next_agent", "end")
        print(f"[Router] 조건부 엣지 → {next_agent}")
        return next_agent

    # ── 노드 구현 ─────────────────────────────

    async def _orchestrator_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        """
        현재 State를 기반으로 다음 실행 Agent를 결정한다.

        첫 호출 시 QueryParser로 질문을 파싱한다.
        이후 State 완성도에 따라 retrieval → analysis → synthesis → end 순으로 라우팅한다.
        """
        iteration = state.get("iteration_count", 0) + 1
        max_iter = state.get("max_iterations", MAX_ITERATIONS)

        print(f"\n[Orchestrator] ===== 반복 #{iteration} / 최대 {max_iter} =====")
        print(f"[Orchestrator] 사용자 질의: {state.get('user_query')!r}")
        print(
            f"[Orchestrator] 현재 State 요약 → "
            f"parsed_query={'있음' if state.get('parsed_query') else '없음'} | "
            f"retrieved_data={'있음' if state.get('retrieved_data') else '없음'} | "
            f"analysis_insights={'있음' if state.get('analysis_insights') else '없음'} | "
            f"final_response={'있음' if state.get('final_response') else '없음'}"
        )

        updates: InvestmentAgentState = {"iteration_count": iteration}

        # 최대 반복 초과 → 강제 종료
        if iteration > max_iter:
            print("[Orchestrator] 최대 반복 횟수 초과 → 워크플로우 강제 종료")
            updates["next_agent"] = "end"
            return updates

        # 첫 호출: Query Parser로 질문 파싱 후 State에 기록
        if not state.get("parsed_query"):
            print("[Orchestrator] Query Parser 호출 중...")
            parsed = await self._query_parser.parse(state.get("user_query", ""))
            updates["parsed_query"] = parsed
            print(
                f"[Orchestrator] 파싱 결과 State 기록 완료 → "
                f"company={parsed['company']!r} | "
                f"intent={parsed['intent']!r} | "
                f"required_data={parsed['required_data']}"
            )

        # 상태 기반 동적 라우팅 결정
        if not state.get("retrieved_data"):
            next_agent = "retrieval"
        elif not state.get("analysis_insights"):
            next_agent = "analysis"
        elif not state.get("final_response"):
            next_agent = "synthesis"
        else:
            next_agent = "end"

        print(f"[Orchestrator] 다음 실행 에이전트 → {next_agent}")
        updates["next_agent"] = next_agent
        return updates

    async def _retrieval_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        """
        required_data 배열을 읽어 _source_handlers 레지스트리에서 핸들러를 조회하고,
        모든 소스를 병렬로 동시 실행하여 수집 결과를 State에 적재한다.

        - 새 소스 추가: _source_handlers 에만 등록하면 자동으로 병렬 실행된다.
        - 각 핸들러에 RETRIEVAL_TIMEOUT_SECS 타임아웃이 적용된다.
        - 부분 실패 허용: 특정 소스 실패·타임아웃이 다른 소스 실행을 중단하지 않는다.
        - required_data 순서대로 retrieved_data가 조립된다.
        """
        parsed: ParsedQuery = state.get("parsed_query") or {}
        company = parsed.get("company") or "전체 시장"
        required_data = parsed.get("required_data", [])
        user_id = state.get("user_id", "unknown")

        print(f"\n[Retrieval] 데이터 수집 시작 | company={company!r} | required_data={required_data}")

        # required_data 순서를 유지하면서 구현된 소스만 선택
        active_sources = [
            src for src in required_data
            if src in IMPLEMENTED_SOURCE_KEYS and src in self._source_handlers
        ]
        ignored = [d for d in required_data if d not in IMPLEMENTED_SOURCE_KEYS]

        print(
            f"[Retrieval] 소스 라우팅 → 활성={active_sources}"
            + (f" | 무시됨={ignored}" if ignored else "")
        )

        if not active_sources:
            print("[Retrieval] 처리 가능한 데이터 소스가 없습니다. 빈 데이터로 진행합니다.")
            return {"retrieved_data": []}

        # ── 타임아웃 적용 병렬 수집 ──────────────────────────────────────────
        print(
            f"[Retrieval] {len(active_sources)}개 소스 병렬 수집 시작 "
            f"(timeout={RETRIEVAL_TIMEOUT_SECS}s/소스)"
        )
        t_start = time.monotonic()

        coros = [
            asyncio.wait_for(
                self._source_handlers[src](company),
                timeout=RETRIEVAL_TIMEOUT_SECS,
            )
            for src in active_sources
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        t_elapsed = time.monotonic() - t_start
        print(
            f"[Retrieval] 병렬 수집 완료 | {len(active_sources)}개 소스 | "
            f"총 소요시간={t_elapsed:.2f}s "
            f"(단일 순차 실행 대비 최대 {len(active_sources)}배 단축 가능)"
        )

        # ── 결과 병합 (required_data 순서 보장, 부분 실패 허용) ───────────────
        retrieved_data: list[dict[str, Any]] = []
        source_statuses: dict[str, str] = {}
        youtube_videos: list[dict] = []

        for source_name, result in zip(active_sources, results):
            if isinstance(result, asyncio.TimeoutError):
                print(
                    f"[Retrieval][{source_name}] 타임아웃 "
                    f"({RETRIEVAL_TIMEOUT_SECS}s 초과) — 해당 소스만 실패 처리"
                )
                source_statuses[source_name] = "timeout"
                retrieved_data.append({
                    "source": source_name,
                    "status": "error",
                    "error": f"timeout after {RETRIEVAL_TIMEOUT_SECS}s",
                    "items": [],
                })
            elif isinstance(result, Exception):
                print(f"[Retrieval][{source_name}] 수집 실패 (부분 실패 허용): {result}")
                traceback.print_exc()
                source_statuses[source_name] = f"error: {result}"
                retrieved_data.append({
                    "source": source_name,
                    "status": "error",
                    "error": str(result),
                    "items": [],
                })
            else:
                print(f"[Retrieval][{source_name}] 수집 성공 | 항목 수: {len(result)}")
                source_statuses[source_name] = "ok"
                retrieved_data.append({
                    "source": source_name,
                    "status": "ok",
                    "items": result,
                })
                if source_name == "유튜브":
                    youtube_videos = result

        print(f"[Retrieval] 전체 수집 완료 | 총 소스 수: {len(retrieved_data)}")

        # ── 투자 심리 지표 산출 (병렬) ────────────────────────────────────────
        await self._attach_signal_metrics(retrieved_data, company=parsed.get("company"))

        # ── DB 저장 ───────────────────────────────────────────────────────────
        if self._db_session:
            news_items = next(
                (r["items"] for r in retrieved_data if r["source"] == "뉴스" and r["status"] == "ok"),
                [],
            )
            await self._persist_collected_data(
                user_id=user_id,
                company=parsed.get("company"),
                intent=parsed.get("intent", "기타"),
                required_data=required_data,
                source_statuses=source_statuses,
                youtube_videos=youtube_videos,
                news_articles=news_items,
            )

        return {"retrieved_data": retrieved_data}

    @staticmethod
    def _format_retrieval_text(retrieved_data: list[dict[str, Any]]) -> str:
        """
        retrieved_data 리스트를 required_data 순서 그대로 포맷팅하여 하나의 텍스트로 반환한다.

        Analysis/Synthesis 노드에서 LLM 컨텍스트 조립 시 활용할 수 있다.
        """
        parts: list[str] = []
        for entry in retrieved_data:
            source = entry["source"]
            if entry["status"] != "ok":
                parts.append(f"[{source}] 수집 실패: {entry.get('error', '알 수 없는 오류')}")
                continue
            items = entry.get("items", [])
            if not items:
                parts.append(f"[{source}] 수집된 항목 없음")
                continue
            if source == "뉴스":
                lines = [item.get("summary_text") or item.get("title", "") for item in items[:5]]
                parts.append(f"[{source}]\n" + "\n".join(f"- {line}" for line in lines if line))
            elif source == "유튜브":
                lines = [
                    f"[{item.get('channel_name', '')}] {item.get('title', '')}"
                    for item in items[:5]
                ]
                parts.append(f"[{source}]\n" + "\n".join(f"- {line}" for line in lines if line))
            else:
                parts.append(f"[{source}] {len(items)}건 수집")
        return "\n\n".join(parts)

    # ── 개별 소스 수집 헬퍼 ──────────────────────────────────────────────────

    async def _fetch_news(self, company: str) -> list[dict[str, Any]]:
        """
        InvestmentNewsCollector를 통해 뉴스 검색 + 본문 수집을 수행한다.

        company가 "전체 시장"이면 Collector 기본 키워드(방산 방위산업 한국 주식)를 사용한다.
        반환 항목마다 summary_text가 포함되어 Retrieval Agent 적재에 바로 사용된다.
        """
        if not self._news_collector:
            print("[Retrieval][뉴스] SERP API 키 미설정 — 빈 결과 반환")
            return []

        target = company if company != "전체 시장" else None
        print(f"[Retrieval][뉴스] 수집 시작 | company={target!r}")

        t0 = time.monotonic()
        items = await self._news_collector.collect(company=target)
        print(f"[Retrieval][뉴스] 기사 {len(items)}건 수집 완료 | 소요시간={time.monotonic() - t0:.2f}s")
        return items

    async def _fetch_youtube(self, company: str) -> list[dict[str, Any]]:
        """
        YouTube Data API v3로 관련 영상을 수집하고 상위 영상의 댓글을 추가로 수집한다.

        published_at은 원본 문자열과 파싱된 datetime 객체를 함께 반환한다.
        """
        if not self._youtube_client:
            print("[Retrieval][유튜브] YouTube API 키 미설정 — 빈 결과 반환")
            return []

        keyword = f"{company} 주식" if company != "전체 시장" else None
        print(f"[Retrieval][유튜브] 영상 검색 중 | keyword={keyword!r}")

        t0 = time.monotonic()
        videos, _, _, total = await self._youtube_client.search(keyword=keyword)

        items: list[dict[str, Any]] = []
        for i, video in enumerate(videos):
            video_id = _extract_video_id(video.video_url)
            published_at_dt = _parse_youtube_datetime(video.published_at)

            comments: list = []
            if self._youtube_comment_client and video_id and i < _MAX_VIDEOS_FOR_COMMENTS:
                print(f"[Retrieval][유튜브] 댓글 수집 중 | video_id={video_id}")
                try:
                    comments = await self._youtube_comment_client.fetch_comments(
                        video_id=video_id,
                        max_count=_MAX_COMMENTS_PER_VIDEO,
                    )
                    print(f"[Retrieval][유튜브] 댓글 {len(comments)}건 수집 | video_id={video_id}")
                except Exception as e:
                    print(f"[Retrieval][유튜브] 댓글 수집 실패 (무시) | video_id={video_id} | {e}")
                    comments = []

            items.append({
                "title": video.title,
                "channel_name": video.channel_name,
                "published_at": video.published_at,       # 원본 문자열
                "published_at_dt": published_at_dt,       # DB 저장용 datetime
                "video_url": video.video_url,
                "thumbnail_url": video.thumbnail_url,
                "video_id": video_id,
                "comments": comments,
            })

        print(
            f"[Retrieval][유튜브] 영상 {len(items)}건 수집 완료 "
            f"(전체 검색결과: {total}건) | 소요시간={time.monotonic() - t0:.2f}s"
        )
        return items

    # ── 투자 심리 지표 산출 ──────────────────────────────────────────────────

    async def _attach_signal_metrics(
        self,
        retrieved_data: list[dict[str, Any]],
        *,
        company: Optional[str],
    ) -> None:
        """
        retrieved_data 각 항목에 'signal' 키를 추가한다 (in-place).

        유튜브: 모든 영상의 댓글 텍스트를 수집하여 감성·키워드·토픽 지표 산출.
        뉴스  : 기사 요약 텍스트로부터 긍·부정 이벤트 및 키워드 지표 산출.

        두 소스의 지표 산출을 asyncio.gather 로 동시 실행한다.
        지표 산출 실패 시 해당 소스의 signal=None 으로 처리하고 워크플로우를 계속 진행한다.
        """
        signal_sources: list[str] = []
        signal_coros = []

        for entry in retrieved_data:
            if entry.get("status") != "ok":
                continue
            src = entry["source"]
            if src == "유튜브":
                # {"text": "...", "author": "...", ...} 구조에서 text 추출
                all_comments: list[str] = [
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for item in entry.get("items", [])
                    for c in item.get("comments", [])
                    if (c.get("text", "") if isinstance(c, dict) else str(c)).strip()
                ]
                signal_sources.append(src)
                signal_coros.append(
                    self._signal_analyzer.analyze_youtube_comments(
                        all_comments, company=company
                    )
                )
            elif src == "뉴스":
                signal_sources.append(src)
                signal_coros.append(
                    self._signal_analyzer.analyze_news(
                        entry.get("items", []), company=company
                    )
                )

        if not signal_coros:
            return

        print(
            f"[Retrieval] 투자 심리 지표 산출 시작 | {len(signal_coros)}개 소스 병렬 실행"
        )
        t_sig = time.monotonic()
        signal_results = await asyncio.gather(*signal_coros, return_exceptions=True)
        print(
            f"[Retrieval] 투자 심리 지표 산출 완료 | 소요={time.monotonic() - t_sig:.2f}s"
        )

        signal_map: dict[str, Any] = dict(zip(signal_sources, signal_results))

        for entry in retrieved_data:
            src = entry["source"]
            if src not in signal_map:
                continue
            sig = signal_map[src]
            if isinstance(sig, Exception):
                print(f"[Retrieval][{src}] 심리 지표 산출 실패 (워크플로우 계속): {sig}")
                traceback.print_exc()
                entry["signal"] = None
            else:
                entry["signal"] = sig

    # ── DB 영속화 ────────────────────────────────────────────────────────────

    async def _persist_collected_data(
        self,
        *,
        user_id: str,
        company: str | None,
        intent: str,
        required_data: list[str],
        source_statuses: dict[str, str],
        youtube_videos: list[dict],
        news_articles: list[dict],
    ) -> None:
        """
        수집 결과를 네 테이블에 저장한다 (모두 PostgreSQL).

          1. investment_youtube_logs           — 워크플로우 실행 로그
          2. investment_youtube_videos         — YouTube 영상 메타데이터
          3. investment_youtube_video_comments — 영상별 댓글
          4. investment_news_contents          — SERP 뉴스 원문 (JSONB)

        예외 발생 시 traceback을 출력하고 워크플로우는 계속 진행한다 (부분 실패 허용).
        """
        print(
            f"\n[RetrievalAgent] [DB] 저장 시작 "
            f"| 영상={len(youtube_videos)}건 | 뉴스={len(news_articles)}건"
        )
        repo = InvestmentYoutubeRepository(self._db_session)

        try:
            # 1. 실행 로그 저장
            log_id = await repo.save_log(
                user_id=user_id,
                company=company,
                intent=intent,
                required_data=required_data,
                source_statuses=source_statuses,
            )

            # 2. YouTube 영상 저장 → (db_video_id, video_url) 목록 반환
            if youtube_videos:
                video_rows = await repo.save_videos(log_id, youtube_videos)

                # 3. 영상별 댓글 저장
                video_map = {url: db_id for db_id, url in video_rows}
                for video in youtube_videos:
                    comments = video.get("comments", [])
                    if not comments:
                        continue
                    db_video_id = video_map.get(video["video_url"])
                    if db_video_id:
                        await repo.save_comments(db_video_id, comments)

            # 4. 뉴스 메타데이터 + 본문 저장
            if news_articles:
                from app.domains.news.adapter.outbound.external.investment_news_collector import DEFAULT_KEYWORD
                keyword_used = f"{company} 주식 뉴스" if company else DEFAULT_KEYWORD
                news_repo = InvestmentNewsRepository(self._db_session)
                await news_repo.save_articles(
                    user_id=user_id,
                    company=company,
                    keyword_used=keyword_used,
                    articles=news_articles,
                )

            # 5. 커밋
            await repo.commit()
            print(f"[RetrievalAgent] [DB] 전체 저장 완료 | log_id={log_id}")

        except Exception:
            print("[RetrievalAgent] [DB] [ERROR] 데이터 저장 실패 (워크플로우 계속 진행):")
            traceback.print_exc()

    async def _analysis_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        """
        수집된 뉴스·YouTube 데이터와 심리 지표로 두 단계 분석을 수행한다.

        1) InvestmentDecisionAnalyzer — deterministic rule 기반 verdict/confidence/direction
           + LLM rationale 생성 → investment_decision State 에 기록
        2) LLM 분석 — outlook / risk / investment_points → analysis_insights State 에 기록
        """
        parsed: ParsedQuery = state.get("parsed_query") or {}
        company = parsed.get("company") or "전체 시장"
        intent = parsed.get("intent", "기타")
        retrieved_data = state.get("retrieved_data", [])

        print(f"\n[AnalysisAgent] 분석 시작 | company={company!r} | intent={intent!r}")

        # ── 신호 추출 ─────────────────────────────────────────────────────────
        news_signal = None
        youtube_signal = None
        news_lines: list[str] = []
        youtube_lines: list[str] = []

        for source in retrieved_data:
            if source.get("status") != "ok":
                continue
            src = source["source"]
            sig = source.get("signal")

            if src == "뉴스":
                for item in source["items"][:5]:
                    news_lines.append(item.get("summary_text") or item.get("title", ""))
                if sig:
                    news_signal = sig
            elif src == "유튜브":
                for item in source["items"][:5]:
                    youtube_lines.append(
                        f"[{item.get('channel_name', '')}] {item.get('title', '')}"
                    )
                if sig:
                    youtube_signal = sig

        print(
            f"[AnalysisAgent] 신호 로드 완료 "
            f"| 뉴스기사={len(news_lines)}건 | 유튜브영상={len(youtube_lines)}건 "
            f"| news_signal={'있음' if news_signal else '없음'} "
            f"| youtube_signal={'있음' if youtube_signal else '없음'}"
        )

        # ── Step 1: Deterministic 투자 판단 ──────────────────────────────────
        decision = await self._decision_analyzer.analyze(
            news_signal=news_signal,
            youtube_signal=youtube_signal,
            company=parsed.get("company"),
            intent=intent,
        )

        # ── Step 2: LLM 종합 분석 (outlook / risk / investment_points) ───────
        news_context = "\n".join(news_lines) if news_lines else "수집된 뉴스 없음"
        youtube_context = "\n".join(youtube_lines) if youtube_lines else "수집된 영상 없음"

        verdict_ko = {"buy": "매수", "hold": "보유", "sell": "매도"}.get(
            decision["verdict"], decision["verdict"]
        )

        system_prompt = """당신은 한국 주식 투자 분석 전문가입니다.
수집된 뉴스, YouTube 영상, 투자 판단 결과를 종합하여 종목을 분석하세요.
반드시 아래 JSON 형식으로만 응답하세요 (마크다운, 코드블록 금지):
{
  "outlook": "종목 전망 (2~3문장, verdict와 confidence 수준을 근거 포함)",
  "risk": "주요 리스크 요인 (2~3문장)",
  "investment_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"]
}"""

        user_prompt = f"""분석 대상: {company}
사용자 질문 의도: {intent}

[투자 판단 결과]
verdict    : {decision['verdict']} ({verdict_ko})
direction  : {decision['direction']}
confidence : {decision['confidence']:.3f}
rationale  : {decision['rationale']}

[수집된 뉴스]
{news_context}

[수집된 YouTube 영상]
{youtube_context}"""

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        raw = response.content.strip()
        print(f"[AnalysisAgent] LLM 응답 수신 | 길이={len(raw)}자")

        try:
            data = json.loads(raw)
            analysis_insights = {
                "outlook": str(data.get("outlook", "")),
                "risk": str(data.get("risk", "")),
                "investment_points": list(data.get("investment_points", [])),
            }
        except json.JSONDecodeError:
            print("[AnalysisAgent] JSON 파싱 실패 — 원문 텍스트로 fallback")
            analysis_insights = {
                "outlook": raw,
                "risk": "",
                "investment_points": [],
            }

        print(f"[AnalysisAgent] 분석 완료 | verdict={decision['verdict']} | 전망={analysis_insights['outlook'][:50]!r}...")
        return {
            "investment_decision": dict(decision),
            "analysis_insights": analysis_insights,
        }

    async def _synthesis_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        """
        investment_decision 을 기반으로 최종 자연어 투자 참고 응답을 생성한다.

        경로 A (정상): investment_decision.verdict 존재
          → verdict·confidence·reasons·risk_factors 기반 LLM 합성
          → LLM은 새 근거 생성 금지, reasons 텍스트화 역할만 수행

        경로 B (fallback): investment_decision 누락
          → analysis_insights 기반 응답, "참고용 분석 결과" 명시

        공통: 면책 문구 자동 부착, verdict/confidence 콘솔 pretty-print
        """
        query = state.get("user_query", "")
        investment_decision = state.get("investment_decision") or {}
        analysis_insights = state.get("analysis_insights") or {}
        parsed: ParsedQuery = state.get("parsed_query") or {}
        company = parsed.get("company") or "전체 시장"
        intent = parsed.get("intent", "기타")

        print(f"\n[SynthesisAgent] 종합 시작 | company={company!r} | intent={intent!r}")

        verdict = investment_decision.get("verdict", "")

        if verdict:
            final_response = await self._synthesize_from_decision(
                query=query,
                company=company,
                intent=intent,
                investment_decision=investment_decision,
            )
        else:
            print("[SynthesisAgent] investment_decision 없음 → analysis_insights fallback")
            final_response = await self._synthesize_fallback(
                query=query,
                company=company,
                intent=intent,
                analysis_insights=analysis_insights,
            )

        _DISCLAIMER = (
            "\n\n※ 본 응답은 투자 권유가 아닌 정보 제공 목적으로만 활용되어야 하며, "
            "투자 판단 및 그에 따른 결과는 전적으로 투자자 본인의 책임입니다."
        )
        final_response = final_response + _DISCLAIMER

        # ── pretty-print ──────────────────────────────────────────────────────
        confidence = investment_decision.get("confidence", 0.0)
        self._print_synthesis_result(
            verdict=verdict or "N/A (fallback)",
            confidence=confidence,
            body=final_response,
        )

        return {"final_response": final_response}

    # ── 합성 경로 A: investment_decision 기반 ─────────────────────────────────

    async def _synthesize_from_decision(
        self,
        *,
        query: str,
        company: str,
        intent: str,
        investment_decision: dict,
    ) -> str:
        """
        investment_decision의 verdict·reasons·risk_factors 만을 사용하여
        자연어 응답을 생성한다. LLM이 새로운 근거를 만들지 못하도록 엄격히 지시한다.
        """
        verdict     = investment_decision["verdict"]
        confidence  = investment_decision["confidence"]
        direction   = investment_decision.get("direction", "neutral")
        rationale   = investment_decision.get("rationale", "")
        reasons     = investment_decision.get("reasons", {})
        risk_factors = investment_decision.get("risk_factors", [])

        verdict_ko  = {"buy": "매수", "hold": "보유", "sell": "매도"}[verdict]
        conf_label  = self._confidence_label(confidence)
        is_conservative = verdict == "hold" and confidence <= 0.3

        print(
            f"[SynthesisAgent] 경로 A (decision 기반) "
            f"| verdict={verdict}({verdict_ko}) | confidence={confidence:.3f}({conf_label})"
            + (" | 보수적판단" if is_conservative else "")
        )

        # 근거 텍스트 구성
        pos_reasons = reasons.get("positive", [])
        neg_reasons = reasons.get("negative", [])
        pos_text = "\n".join(f"  - {r}" for r in pos_reasons) if pos_reasons else "  - 없음"
        neg_text = "\n".join(f"  - {r}" for r in neg_reasons) if neg_reasons else "  - 없음"
        risk_text = "\n".join(f"  - {r}" for r in risk_factors) if risk_factors else "  - 없음"

        conservative_note = (
            "\n[주의] 이 판단은 수집된 데이터가 충분하지 않아 신호 부족으로 인한 "
            "보수적 기본값입니다. 추가 정보 확인을 권장합니다."
            if is_conservative else ""
        )

        system_prompt = """당신은 한국 주식 투자 어드바이저입니다.
아래에 제공된 투자 판단 결과와 근거를 사용자 친화적 한국어 서술로 변환하세요.

절대 규칙:
1. verdict(매수/보유/매도) 표현을 완곡하게 바꾸거나 의미를 흐리면 안 됩니다.
2. 제공된 reasons와 risk_factors 이외의 새로운 근거나 수치를 생성하지 마세요.
3. 응답 구조: [결론 한 줄] → [긍정 근거 요약] → [부정·리스크 요약] (총 2~4문단)
4. 마크다운 헤더(#) 없이 일반 텍스트로만 작성하세요."""

        user_prompt = f"""사용자 질문: {query}
분석 대상: {company}
질문 의도: {intent}
{conservative_note}

[확정된 투자 판단 — 변경 불가]
  의견(verdict)  : {verdict_ko} ({verdict})
  방향성         : {direction}
  확신도         : {confidence:.1%} ({conf_label})
  판단 근거 요약 : {rationale}

[긍정 근거 — 이 내용만 사용하세요]
{pos_text}

[부정 근거 — 이 내용만 사용하세요]
{neg_text}

[리스크 요인 — 이 내용만 사용하세요]
{risk_text}

위 정보를 바탕으로 verdict를 가장 먼저 명확하게 전달하고,
근거와 리스크를 자연스럽게 서술하는 2~4문단 한국어 응답을 작성하세요.
새로운 사실이나 수치를 추가하지 마세요."""

        print("[SynthesisAgent] LLM 호출 중 (경로 A)...")
        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        text = response.content.strip()
        print(f"[SynthesisAgent] LLM 응답 수신 | 길이={len(text)}자")
        return text

    # ── 합성 경로 B: analysis_insights fallback ───────────────────────────────

    async def _synthesize_fallback(
        self,
        *,
        query: str,
        company: str,
        intent: str,
        analysis_insights: dict,
    ) -> str:
        """investment_decision 누락 시 analysis_insights 기반 fallback 응답을 생성한다."""
        investment_points = analysis_insights.get("investment_points", [])
        points_text = (
            "\n".join(f"  - {p}" for p in investment_points) if investment_points else "  - 없음"
        )

        system_prompt = """당신은 한국 주식 투자 어드바이저입니다.
아래 분석 결과를 바탕으로 사용자 질문에 대한 참고용 응답을 작성하세요.
투자 판단 데이터가 부족하여 정량 의견 대신 정성 분석만 제공됩니다.
마크다운 헤더(#) 없이 일반 텍스트로 작성하세요."""

        user_prompt = f"""[참고용 분석 결과 — 투자 판단 데이터 부족]
사용자 질문: {query}
분석 대상: {company}
질문 의도: {intent}

전망: {analysis_insights.get('outlook', '정보 없음')}
리스크: {analysis_insights.get('risk', '정보 없음')}
투자 포인트:
{points_text}

이 결과는 정량 신호 부족으로 참고용 분석에 해당합니다.
이를 명시하고 2~3문단으로 사용자 친화적 응답을 작성하세요."""

        print("[SynthesisAgent] LLM 호출 중 (경로 B fallback)...")
        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        text = response.content.strip()
        print(f"[SynthesisAgent] LLM fallback 응답 수신 | 길이={len(text)}자")
        return text

    # ── 헬퍼 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        """confidence 수치를 사람이 읽기 쉬운 확신 수준 레이블로 변환한다."""
        if confidence >= 0.7:
            return "높은 확신"
        if confidence >= 0.4:
            return "일정 수준의 가능성"
        return "불확실성이 높은 상태"

    @staticmethod
    def _print_synthesis_result(verdict: str, confidence: float, body: str) -> None:
        """최종 응답 요약을 콘솔에 pretty-print 한다."""
        preview = body[:120].replace("\n", " ")
        print(
            f"\n[SynthesisAgent] ══ 최종 응답 ══════════════════════════════\n"
            f"  verdict    : {verdict}\n"
            f"  confidence : {confidence:.4f} "
            f"({LangGraphInvestmentWorkflow._confidence_label(confidence)})\n"
            f"  본문 미리보기: {preview}...\n"
            f"  전체 길이  : {len(body)}자\n"
            f"  ══════════════════════════════════════════════════════"
        )
