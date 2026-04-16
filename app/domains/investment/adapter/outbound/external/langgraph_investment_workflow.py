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
from typing import Any, Awaitable, Callable, Optional, TypedDict
from urllib.parse import parse_qs, urlparse

import json

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.investment.adapter.outbound.external.investment_source_registry import (
    IMPLEMENTED_SOURCE_KEYS,
)
from app.domains.investment.adapter.outbound.external.llm_query_parser import LLMQueryParser
from app.domains.investment.adapter.outbound.external.youtube_sentiment_analyzer import (
    YoutubeSentimentAnalyzer,
)
from app.domains.investment.adapter.outbound.external.news_signal_analyzer import (
    NewsSignalAnalyzer,
)
from app.domains.investment.adapter.outbound.external.investment_decision_analyzer import (
    InvestmentDecisionAnalyzer,
)
from app.domains.investment.domain.value_object.youtube_sentiment_metrics import (
    empty_youtube_sentiment,
    empty_news_signal,
)
from app.domains.investment.domain.value_object.investment_decision import (
    conservative_fallback,
)
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

# Retrieval 단계에서 단일 소스 핸들러에 적용하는 최대 실행 시간 (초)
_RETRIEVAL_TIMEOUT_SECONDS: int = 30

# 영상당 최대 수집 댓글 수 / 댓글을 수집할 최대 영상 수
_MAX_COMMENTS_PER_VIDEO = 5
_MAX_VIDEOS_FOR_COMMENTS = 3


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
        self._youtube_sentiment_analyzer = YoutubeSentimentAnalyzer(llm=self._llm)
        self._news_signal_analyzer = NewsSignalAnalyzer(llm=self._llm)
        self._investment_decision_analyzer = InvestmentDecisionAnalyzer(llm=self._llm)
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
            print(f"[Orchestrator] 최대 반복 횟수 초과 → 워크플로우 강제 종료")
            updates["next_agent"] = "end"
            return updates

        # 첫 호출: Query Parser로 질문 파싱 후 State에 기록
        if not state.get("parsed_query"):
            print(f"[Orchestrator] Query Parser 호출 중...")
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

    # ── 소스 핸들러 레지스트리 ────────────────────────────────────────────────
    # SOURCE_REGISTRY 에 등록된 키와 1:1 대응한다.
    # 새 소스를 추가할 때 이 dict 에만 항목을 추가하면 병렬 실행에 자동 편입된다.
    # handler signature: Callable[[Optional[str]], Awaitable[list[dict]]]

    @property
    def _source_handlers(self) -> dict[str, Callable[[Optional[str]], Awaitable[list[dict[str, Any]]]]]:
        return {
            "뉴스": self._fetch_news,
            "유튜브": self._fetch_youtube,
            # 확장 포인트: 새 소스는 여기에만 추가
            # "종목": self._fetch_stock,
        }

    async def _run_source_with_timeout(
        self,
        source_name: str,
        company: str,
    ) -> tuple[str, list[dict[str, Any]] | Exception]:
        """
        단일 소스 핸들러를 타임아웃을 걸고 실행한다.

        - 성공: (source_name, list) 반환
        - 예외/타임아웃: (source_name, Exception) 반환 — 호출자가 부분 실패 처리
        """
        handler = self._source_handlers.get(source_name)
        if handler is None:
            print(f"[Retrieval][{source_name}] 핸들러 미등록 — 실패 처리")
            return source_name, RuntimeError(f"핸들러 없음: {source_name}")

        start = time.monotonic()
        print(f"[Retrieval][{source_name}] 수집 시작")
        try:
            result = await asyncio.wait_for(
                handler(company),
                timeout=_RETRIEVAL_TIMEOUT_SECONDS,
            )
            elapsed = time.monotonic() - start
            print(f"[Retrieval][{source_name}] 수집 완료 | {elapsed:.2f}s | 항목 수: {len(result)}")
            return source_name, result
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            print(
                f"[Retrieval][{source_name}] 타임아웃 ({elapsed:.2f}s > {_RETRIEVAL_TIMEOUT_SECONDS}s) "
                f"— 해당 소스만 실패 처리"
            )
            return source_name, TimeoutError(
                f"{source_name} 수집 타임아웃 ({_RETRIEVAL_TIMEOUT_SECONDS}s 초과)"
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            print(f"[Retrieval][{source_name}] 예외 ({elapsed:.2f}s): {exc!r} — 해당 소스만 실패 처리")
            traceback.print_exc()
            return source_name, exc

    async def _retrieval_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        """
        required_data 에 명시된 소스를 SOURCE_REGISTRY 핸들러 레지스트리에서 찾아
        모두 동시에 실행하고 결과를 required_data 순서대로 State에 적재한다.

        - 모든 핸들러는 asyncio.wait_for로 감싸 개별 타임아웃이 적용된다.
        - 한 핸들러의 예외·타임아웃이 다른 핸들러를 중단시키지 않는다 (부분 실패 허용).
        - 미구현 소스(SOURCE_REGISTRY에 없는 키)는 조용히 무시한다.
        """
        parsed: ParsedQuery = state.get("parsed_query") or {}
        company = parsed.get("company") or "전체 시장"
        required_data = parsed.get("required_data", [])
        user_id = state.get("user_id", "unknown")

        print(f"\n[Retrieval] 데이터 수집 시작 | company={company!r} | required_data={required_data}")

        # 구현된 소스만 병렬 실행 대상으로 선별
        active_sources = [src for src in required_data if src in IMPLEMENTED_SOURCE_KEYS]
        ignored = [src for src in required_data if src not in IMPLEMENTED_SOURCE_KEYS]
        if ignored:
            print(f"[Retrieval] 미구현 소스 무시: {ignored}")

        if not active_sources:
            print(f"[Retrieval] 처리 가능한 데이터 소스가 없습니다. 빈 데이터로 진행합니다.")
            return {"retrieved_data": []}

        # ── 병렬 실행 (모든 소스를 동시에, 개별 타임아웃 적용) ────────────────
        total_start = time.monotonic()
        print(f"[Retrieval] 병렬 수집 시작 | 소스={active_sources} | 타임아웃={_RETRIEVAL_TIMEOUT_SECONDS}s/소스")

        raw_results: list[tuple[str, list[dict[str, Any]] | Exception]] = await asyncio.gather(
            *[self._run_source_with_timeout(src, company) for src in active_sources]
        )

        total_elapsed = time.monotonic() - total_start
        print(f"[Retrieval] 병렬 수집 완료 | 총 소요시간: {total_elapsed:.2f}s | 소스 수: {len(active_sources)}")

        # ── 결과 병합 (required_data 순서 보존) ──────────────────────────────
        result_map: dict[str, list[dict[str, Any]] | Exception] = {
            src: result for src, result in raw_results
        }

        retrieved_data: list[dict[str, Any]] = []
        source_statuses: dict[str, str] = {}
        youtube_videos: list[dict] = []

        for source_name in active_sources:   # required_data 순서대로 순회
            result = result_map[source_name]
            if isinstance(result, Exception):
                source_statuses[source_name] = f"error: {result}"
                retrieved_data.append({
                    "source": source_name,
                    "status": "error",
                    "error": str(result),
                    "items": [],
                })
            else:
                source_statuses[source_name] = "ok"
                retrieved_data.append({
                    "source": source_name,
                    "status": "ok",
                    "items": result,
                })
                if source_name == "유튜브":
                    youtube_videos = result

        success_count = sum(1 for r in retrieved_data if r["status"] == "ok")
        print(
            f"[Retrieval] 결과 집계 완료 | 성공={success_count}/{len(retrieved_data)} "
            f"| 전체 소요={total_elapsed:.2f}s"
        )

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

    # ── 개별 소스 수집 헬퍼 ──────────────────────────────────────────────────

    async def _fetch_news(self, company: str) -> list[dict[str, Any]]:
        """
        InvestmentNewsCollector를 통해 뉴스 검색 + 본문 수집을 수행한다.

        company가 "전체 시장"이면 Collector 기본 키워드(방산 방위산업 한국 주식)를 사용한다.
        반환 항목마다 summary_text가 포함되어 Retrieval Agent 적재에 바로 사용된다.
        """
        if not self._news_collector:
            print(f"[Retrieval][뉴스] SERP API 키 미설정 — 빈 결과 반환")
            return []

        target = company if company != "전체 시장" else None
        print(f"[Retrieval][뉴스] 검색 대상={target!r}")

        items = await self._news_collector.collect(company=target)
        print(f"[Retrieval][뉴스] 기사 {len(items)}건 수집 완료")
        return items

    async def _fetch_youtube(self, company: str) -> list[dict[str, Any]]:
        """
        YouTube Data API v3로 관련 영상을 수집하고 상위 영상의 댓글을 추가로 수집한다.

        published_at은 원본 문자열과 파싱된 datetime 객체를 함께 반환한다.
        """
        if not self._youtube_client:
            print(f"[Retrieval][유튜브] YouTube API 키 미설정 — 빈 결과 반환")
            return []

        keyword = f"{company} 주식" if company != "전체 시장" else None
        print(f"[Retrieval][유튜브] 영상 검색 중 | keyword={keyword!r}")

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

        print(f"[Retrieval][유튜브] 영상 {len(items)}건 수집 완료 (전체 검색결과: {total}건)")
        return items

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
        수집된 뉴스·YouTube 데이터를 분석하여 투자 인사이트를 State에 적재한다.

        세 단계로 진행한다:
          1) 감성/신호 분석 (병렬): YouTube 댓글 감성 지표 + 뉴스 투자 신호
          2) 통합 LLM 분석 + 투자 판단 (병렬):
             - 통합 LLM: 원문 + 지표로 전망·리스크·투자포인트 생성
             - 투자 판단: deterministic rule로 direction/confidence/verdict 산출

        analysis_insights 키:
          - outlook, risk, investment_points  (통합 LLM 결과)
          - youtube_sentiment                 (YoutubeSentimentMetrics)
          - news_signal                       (NewsSignalMetrics)
          - investment_decision               (InvestmentDecision)
        """
        parsed: ParsedQuery = state.get("parsed_query") or {}
        company = parsed.get("company") or "전체 시장"
        intent = parsed.get("intent", "기타")
        retrieved_data = state.get("retrieved_data", [])

        print(f"\n[AnalysisAgent] 분석 시작 | company={company!r} | intent={intent!r}")

        # ── retrieval_data에서 소스별 원문 분리 ──────────────────────────────
        news_items: list[dict] = []
        youtube_items: list[dict] = []
        all_comments: list[dict] = []

        for source in retrieved_data:
            if source.get("status") != "ok":
                continue
            if source["source"] == "뉴스":
                news_items = source["items"]
            elif source["source"] == "유튜브":
                youtube_items = source["items"]
                for video in youtube_items:
                    all_comments.extend(video.get("comments", []))

        print(
            f"[AnalysisAgent] 데이터 현황 | "
            f"뉴스={len(news_items)}건 | 유튜브 영상={len(youtube_items)}건 | 댓글={len(all_comments)}건"
        )

        # ── 1단계: 감성/신호 분석 (병렬) ────────────────────────────────────
        print(f"[AnalysisAgent] 1단계: 감성·신호 분석 병렬 실행 중...")
        sentiment_result, signal_result = await asyncio.gather(
            self._youtube_sentiment_analyzer.analyze(all_comments, company),
            self._news_signal_analyzer.analyze(news_items, company),
            return_exceptions=True,
        )

        if isinstance(sentiment_result, Exception):
            print(f"[AnalysisAgent] YouTube 감성 분석 실패 (빈 결과로 대체): {sentiment_result!r}")
            sentiment_result = empty_youtube_sentiment(volume=len(all_comments))

        if isinstance(signal_result, Exception):
            print(f"[AnalysisAgent] 뉴스 신호 분석 실패 (빈 결과로 대체): {signal_result!r}")
            signal_result = empty_news_signal()

        youtube_sentiment = sentiment_result
        news_signal = signal_result

        # ── 2단계: 통합 LLM 분석 + 투자 판단 (병렬) ─────────────────────────
        print(f"[AnalysisAgent] 2단계: 통합 LLM 분석 + 투자 판단 병렬 실행 중...")
        llm_result, decision_result = await asyncio.gather(
            self._run_integrated_llm_analysis(
                company, intent, news_items, youtube_items, youtube_sentiment, news_signal
            ),
            self._investment_decision_analyzer.analyze(
                youtube_sentiment=youtube_sentiment,
                news_signal=news_signal,
                company=company,
                intent=intent,
            ),
            return_exceptions=True,
        )

        if isinstance(llm_result, Exception):
            print(f"[AnalysisAgent] 통합 LLM 분석 실패 (빈 결과로 대체): {llm_result!r}")
            llm_result = {"outlook": "", "risk": "", "investment_points": []}

        if isinstance(decision_result, Exception):
            print(f"[AnalysisAgent] 투자 판단 실패 (보수적 fallback): {decision_result!r}")
            decision_result = conservative_fallback()

        analysis_insights = {
            **llm_result,
            "youtube_sentiment": youtube_sentiment,
            "news_signal": news_signal,
            "investment_decision": decision_result,
        }

        print(
            f"[AnalysisAgent] 분석 완료 | "
            f"verdict={decision_result.get('verdict', '?')} | "
            f"confidence={decision_result.get('confidence', 0):.1%} | "
            f"전망={llm_result.get('outlook', '')[:40]!r}..."
        )
        return {"analysis_insights": analysis_insights}

    async def _run_integrated_llm_analysis(
        self,
        company: str,
        intent: str,
        news_items: list[dict],
        youtube_items: list[dict],
        youtube_sentiment: Any,
        news_signal: Any,
    ) -> dict[str, Any]:
        """
        원문 데이터 + 감성/신호 지표를 LLM에 전달하여
        outlook / risk / investment_points 를 생성한다.
        """
        news_lines = [
            item.get("summary_text") or item.get("title", "")
            for item in news_items[:5]
        ]
        youtube_lines = [
            f"[{v.get('channel_name', '')}] {v.get('title', '')}"
            for v in youtube_items[:5]
        ]
        news_context = "\n".join(news_lines) if news_lines else "수집된 뉴스 없음"
        youtube_context = "\n".join(youtube_lines) if youtube_lines else "수집된 영상 없음"

        dist = youtube_sentiment["sentiment_distribution"]
        sentiment_summary = (
            f"긍정 {dist['positive']:.0%} / 중립 {dist['neutral']:.0%} / 부정 {dist['negative']:.0%} "
            f"(심리점수: {youtube_sentiment['sentiment_score']:+.2f})"
        )
        bullish_kw = ", ".join(youtube_sentiment["bullish_keywords"][:5]) or "없음"
        bearish_kw = ", ".join(youtube_sentiment["bearish_keywords"][:5]) or "없음"

        pos_events = "\n".join(
            f"  [{e['impact'].upper()}] {e['event']}"
            for e in news_signal["positive_events"]
        ) or "  없음"
        neg_events = "\n".join(
            f"  [{e['impact'].upper()}] {e['event']}"
            for e in news_signal["negative_events"]
        ) or "  없음"

        print(f"[AnalysisAgent] 통합 LLM 컨텍스트 구성 | 뉴스={len(news_lines)}건 | 유튜브={len(youtube_lines)}건")

        system_prompt = """당신은 한국 주식 투자 분석 전문가입니다.
수집된 뉴스, YouTube 영상 정보 및 투자 심리 지표를 종합하여 종목을 분석하세요.
반드시 아래 JSON 형식으로만 응답하세요 (마크다운, 코드블록 금지):
{
  "outlook": "종목 전망 (2~3문장, 구체적 근거 포함)",
  "risk": "주요 리스크 요인 (2~3문장)",
  "investment_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"]
}"""

        user_prompt = f"""분석 대상: {company}
사용자 질문 의도: {intent}

[수집된 뉴스]
{news_context}

[수집된 YouTube 영상]
{youtube_context}

[YouTube 댓글 투자 심리 지표]
감성 분포: {sentiment_summary}
강세 키워드: {bullish_kw}
약세 키워드: {bearish_kw}
주요 화제: {', '.join(youtube_sentiment['topics'][:3]) or '없음'}

[뉴스 투자 신호]
긍정 이벤트:
{pos_events}
부정 이벤트:
{neg_events}
핵심 키워드: {', '.join(news_signal['keywords'][:5]) or '없음'}"""

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        raw = response.content.strip()
        print(f"[AnalysisAgent] 통합 LLM 응답 수신 | 길이={len(raw)}자")

        try:
            data = json.loads(raw)
            return {
                "outlook": str(data.get("outlook", "")),
                "risk": str(data.get("risk", "")),
                "investment_points": list(data.get("investment_points", [])),
            }
        except json.JSONDecodeError:
            print(f"[AnalysisAgent] 통합 LLM JSON 파싱 실패 — 원문 텍스트로 fallback")
            return {"outlook": raw, "risk": "", "investment_points": []}

    async def _synthesis_node(self, state: InvestmentAgentState) -> InvestmentAgentState:
        """
        investment_decision을 기반으로 사용자 친화적 최종 답변을 생성한다.

        우선순위:
          1. analysis_insights.investment_decision 이 있으면 이를 기반으로 구성
             → verdict 명시 → reasons 기반 근거 → 리스크 → 면책 문구
          2. investment_decision 이 없으면 outlook/risk/investment_points 로 fallback
             → 첫 문장에 "참고용 분석 결과"임을 명시

        verdict, confidence, direction 은 이 단계에서 절대 변경하지 않는다.
        """
        query = state.get("user_query", "")
        analysis_insights = state.get("analysis_insights", {})
        parsed: ParsedQuery = state.get("parsed_query") or {}
        company = parsed.get("company") or "전체 시장"
        intent = parsed.get("intent", "기타")

        print(f"\n[SynthesisAgent] 응답 종합 시작 | query={query!r} | company={company!r}")

        investment_decision = analysis_insights.get("investment_decision")
        has_decision = bool(investment_decision and investment_decision.get("verdict"))

        if has_decision:
            print(
                f"[SynthesisAgent] investment_decision 확인 | "
                f"verdict={investment_decision['verdict']} | "
                f"confidence={investment_decision.get('confidence', 0):.1%} | "
                f"direction={investment_decision.get('direction', '?')}"
            )
            print(f"[SynthesisAgent] decision 기반 응답 생성 중...")
            body = await self._synthesize_from_decision(
                query=query,
                company=company,
                intent=intent,
                decision=investment_decision,
            )
            mode = "decision"
        else:
            print(f"[SynthesisAgent] investment_decision 없음 → LLM 분석 결과 fallback")
            body = await self._synthesize_from_analysis(
                query=query,
                company=company,
                intent=intent,
                analysis_insights=analysis_insights,
            )
            mode = "fallback"

        # ── 면책 문구 자동 부착 ────────────────────────────────────────────
        DISCLAIMER = (
            "\n\n※ 본 응답은 투자 권유가 아닌 정보 제공 목적으로만 활용되어야 하며, "
            "투자 판단 및 그에 따른 결과는 전적으로 투자자 본인의 책임입니다."
        )
        final_response = body + DISCLAIMER

        # ── pretty-print ───────────────────────────────────────────────────
        verdict = investment_decision.get("verdict", "N/A") if has_decision else "N/A"
        confidence = investment_decision.get("confidence", 0.0) if has_decision else 0.0
        verdict_label = {"buy": "매수(BUY)", "sell": "매도(SELL)", "hold": "보유(HOLD)"}.get(
            verdict, verdict
        )

        print(f"\n[SynthesisAgent] ===== 최종 응답 =====")
        print(f"  모드      : {'decision 기반' if mode == 'decision' else 'fallback(분석 결과 기반)'}")
        print(f"  종목      : {company}")
        print(f"  의견      : {verdict_label}")
        print(f"  신뢰도    : {confidence:.1%}")
        print(f"  응답 길이  : {len(final_response)}자")
        print(f"  본문 앞 150자 :\n  {final_response[:150]!r}")
        print(f"[SynthesisAgent] ====================\n")

        return {"final_response": final_response}

    async def _synthesize_from_decision(
        self,
        query: str,
        company: str,
        intent: str,
        decision: dict[str, Any],
    ) -> str:
        """
        investment_decision(verdict/confidence/direction/reasons/risk_factors)을 기반으로
        사용자 친화적 최종 응답 본문을 생성한다.

        LLM은 제공된 reasons만 문장으로 풀어쓰며, 새로운 근거를 생성하지 않는다.
        """
        verdict = decision.get("verdict", "hold")
        confidence = decision.get("confidence", 0.0)
        direction = decision.get("direction", "neutral")
        reasons = decision.get("reasons", {})
        risk_factors = decision.get("risk_factors", [])

        verdict_kr = {"buy": "매수", "sell": "매도", "hold": "보유"}.get(verdict, "보유")
        direction_kr = {"bullish": "강세", "bearish": "약세", "neutral": "중립"}.get(
            direction, "중립"
        )

        # 확신 수준 표현
        if confidence >= 0.7:
            confidence_desc = "높은 확신"
        elif confidence >= 0.4:
            confidence_desc = "일정 수준의 가능성"
        else:
            confidence_desc = "불확실성이 높은 상태"

        # hold + 낮은 confidence → 보수적 판단 안내
        conservative_note = (
            "\n[주의] 현재 신호 부족으로 인한 보수적 판단입니다. "
            "추가적인 시장 정보 확인 후 판단하시길 권고합니다."
            if (verdict == "hold" and confidence <= 0.3)
            else ""
        )

        pos_reasons = reasons.get("positive", [])
        neg_reasons = reasons.get("negative", [])
        pos_text = "\n".join(f"- {r}" for r in pos_reasons) if pos_reasons else "- 해당 없음"
        neg_text = "\n".join(f"- {r}" for r in neg_reasons) if neg_reasons else "- 해당 없음"
        risk_text = (
            "\n".join(f"- {r}" for r in risk_factors) if risk_factors else "- 해당 없음"
        )

        print(
            f"[SynthesisAgent] 프롬프트 구성 | verdict={verdict_kr} | "
            f"긍정근거={len(pos_reasons)}건 | 부정근거={len(neg_reasons)}건 | "
            f"리스크={len(risk_factors)}건"
        )

        system_prompt = (
            "당신은 투자 정보 제공 전문가입니다.\n"
            "아래 투자 판단 데이터를 바탕으로 사용자에게 명확하고 친절한 한국어 설명을 작성하세요.\n\n"
            "작성 규칙:\n"
            "- 첫 문장에 verdict(매수/보유/매도)를 명확히 제시할 것 — 완곡 표현 금지\n"
            "- 제공된 근거(reasons)만 사용하고, 새로운 근거를 창작하지 말 것\n"
            "- 2~4개 문단 구성: 결론(verdict) → 긍정 근거 → 부정 근거 및 리스크\n"
            "- 마크다운 헤더(#) 없이 일반 텍스트로 작성\n"
            "- 면책 문구는 직접 작성하지 말 것 (자동으로 추가됨)"
        )

        user_prompt = (
            f"사용자 질문: {query}\n"
            f"분석 대상: {company} | 질문 의도: {intent}\n\n"
            f"[투자 판단]\n"
            f"의견: {verdict_kr}({verdict.upper()})\n"
            f"방향성: {direction_kr} | 신뢰도: {confidence:.1%}({confidence_desc})"
            f"{conservative_note}\n\n"
            f"[긍정 근거]\n{pos_text}\n\n"
            f"[부정 근거]\n{neg_text}\n\n"
            f"[리스크 요인]\n{risk_text}\n\n"
            f"위 정보를 바탕으로 설명하세요. "
            f"첫 문장에 '{verdict_kr}' 의견을 명확히 표현하고, 제공된 근거만 활용하세요."
        )

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        result = response.content.strip()
        print(f"[SynthesisAgent] decision 기반 LLM 응답 수신 | 길이={len(result)}자")
        return result

    async def _synthesize_from_analysis(
        self,
        query: str,
        company: str,
        intent: str,
        analysis_insights: dict[str, Any],
    ) -> str:
        """
        investment_decision 누락 시 outlook/risk/investment_points 로 fallback 응답을 생성한다.
        첫 문장에 반드시 '참고용 분석 결과'임을 명시한다.
        """
        investment_points = analysis_insights.get("investment_points", [])
        points_text = (
            "\n".join(f"  - {p}" for p in investment_points)
            if investment_points
            else "  - 없음"
        )

        system_prompt = (
            "당신은 친절하고 전문적인 한국 주식 투자 어드바이저입니다.\n"
            "투자 판단 신호가 부족하여 참고용 분석 결과만 제공하는 상황입니다.\n\n"
            "작성 규칙:\n"
            "- 첫 문장에 '본 응답은 참고용 분석 결과입니다'를 반드시 포함할 것\n"
            "- 3~5문단 분량으로 작성\n"
            "- 마크다운 헤더(#) 없이 일반 텍스트로 작성"
        )

        user_prompt = (
            f"사용자 질문: {query}\n"
            f"분석 대상: {company} | 질문 의도: {intent}\n\n"
            f"[분석 결과 (참고용)]\n"
            f"전망: {analysis_insights.get('outlook', '정보 없음')}\n"
            f"리스크: {analysis_insights.get('risk', '정보 없음')}\n"
            f"핵심 투자 포인트:\n{points_text}\n\n"
            "위 분석을 바탕으로 응답을 작성하세요."
        )

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])
        result = response.content.strip()
        print(f"[SynthesisAgent] fallback LLM 응답 수신 | 길이={len(result)}자")
        return result
