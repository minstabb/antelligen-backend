"""
LLM 기반 투자 심리 지표 산출 어댑터.

Adapter Layer (Outbound / External) — ChatOpenAI 단일 배치 호출로
감성 분류·키워드 추출·이벤트 분류를 수행한다.

성능 목표: 50~250건 댓글 기준 10초 이내 완료 (단일 배치 LLM 호출).

댓글 구조 (investment_youtube_video_comments JSONB):
  {"text": "댓글 내용", "author": "작성자", "like_count": 3, "published_at": "..."}
"""

import json
import time
from typing import Optional

from langchain_openai import ChatOpenAI

from app.domains.investment.application.port.investment_signal_port import InvestmentSignalPort
from app.domains.investment.domain.value_object.news_signal_metrics import (
    NewsEvent,
    NewsSignalMetrics,
)
from app.domains.investment.domain.value_object.youtube_signal_metrics import (
    SentimentDistribution,
    YoutubeSignalMetrics,
)

# 단일 배치 최대 댓글 수 (토큰 예산 조절)
_MAX_COMMENTS_PER_BATCH = 200
# 댓글 1건당 최대 문자 수 (토큰 절약)
_MAX_COMMENT_CHARS = 150
# 뉴스 기사 최대 처리 건수
_MAX_NEWS_ITEMS = 10
# 기사 1건당 최대 문자 수
_MAX_NEWS_CHARS = 300


def _empty_youtube_metrics() -> YoutubeSignalMetrics:
    return YoutubeSignalMetrics(
        sentiment_distribution=SentimentDistribution(positive=0.0, neutral=1.0, negative=0.0),
        sentiment_score=0.0,
        bullish_keywords=[],
        bearish_keywords=[],
        topics=[],
        volume=0,
    )


def _empty_news_metrics() -> NewsSignalMetrics:
    return NewsSignalMetrics(positive_events=[], negative_events=[], keywords=[])


class InvestmentSignalAnalyzer(InvestmentSignalPort):
    """ChatOpenAI 기반 투자 심리 지표 산출 구현체."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        # temperature=0 — 결정론적 분류 결과를 위해 고정
        self._llm = ChatOpenAI(api_key=api_key, model=model, temperature=0)

    # ── 유튜브 댓글 감성 분석 ────────────────────────────────────────────────

    async def analyze_youtube_comments(
        self,
        comments: list[str],
        company: Optional[str] = None,
    ) -> YoutubeSignalMetrics:
        """
        유튜브 댓글 리스트를 LLM에 배치 전달하여 감성 분포·키워드·토픽을 산출한다.

        Returns:
            YoutubeSignalMetrics — 빈 입력 시 neutral=1.0, volume=0 인 기본값 반환.
        Raises:
            Exception — LLM 호출 실패 또는 JSON 파싱 오류 시 그대로 전파.
        """
        if not comments:
            print("[SignalAnalyzer][유튜브] 입력 댓글 0건 → 기본 지표 반환")
            return _empty_youtube_metrics()

        sampled = comments[:_MAX_COMMENTS_PER_BATCH]
        truncated = [c[:_MAX_COMMENT_CHARS].strip() for c in sampled if c.strip()]
        company_label = company or "주식"

        print(
            f"[SignalAnalyzer][유튜브] 감성 분석 시작 "
            f"| 댓글={len(truncated)}건 (전체 {len(comments)}건) | company={company_label!r}"
        )
        t0 = time.monotonic()

        system_prompt = (
            "당신은 한국 주식 투자 감성 분석 전문가입니다. "
            "반드시 JSON만 응답하고 마크다운·코드블록은 사용하지 마세요."
        )
        user_prompt = f"""다음은 [{company_label}] 관련 유튜브 댓글 {len(truncated)}건입니다.

{chr(10).join(f'{i + 1}. {t}' for i, t in enumerate(truncated))}

아래 JSON 형식으로만 응답하세요:
{{
  "positive_count": <긍정 댓글 수 int>,
  "neutral_count": <중립 댓글 수 int>,
  "negative_count": <부정 댓글 수 int>,
  "bullish_keywords": ["키워드1", "키워드2", ...],
  "bearish_keywords": ["키워드1", "키워드2", ...],
  "topics": ["토픽1", "토픽2", "토픽3", "토픽4", "토픽5"]
}}

분류 기준:
- 긍정: 매수 추천, 상승 기대, 호재, 긍정적 전망 표현
- 부정: 매도 추천, 하락 우려, 악재, 부정적 전망 표현
- 중립: 단순 정보, 질문, 분류 불가
- bullish_keywords: 긍정 댓글에서 자주 등장하는 핵심 명사·투자 키워드 TOP 10
- bearish_keywords: 부정 댓글에서 자주 등장하는 핵심 명사·투자 키워드 TOP 10
- topics: 전체 댓글의 주요 토픽 TOP 5 (감성 무관)"""

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        elapsed = time.monotonic() - t0
        raw = response.content.strip()
        print(f"[SignalAnalyzer][유튜브] LLM 응답 수신 | 소요={elapsed:.2f}s | 길이={len(raw)}자")

        data = json.loads(raw)
        pos = int(data.get("positive_count", 0))
        neu = int(data.get("neutral_count", 0))
        neg = int(data.get("negative_count", 0))
        total = pos + neu + neg or 1

        metrics = YoutubeSignalMetrics(
            sentiment_distribution=SentimentDistribution(
                positive=round(pos / total, 3),
                neutral=round(neu / total, 3),
                negative=round(neg / total, 3),
            ),
            sentiment_score=round((pos - neg) / total, 3),
            bullish_keywords=list(data.get("bullish_keywords", []))[:10],
            bearish_keywords=list(data.get("bearish_keywords", []))[:10],
            topics=list(data.get("topics", []))[:5],
            volume=len(comments),
        )

        print(
            f"[SignalAnalyzer][유튜브] 지표 산출 완료\n"
            f"  sentiment_distribution : "
            f"긍정={metrics['sentiment_distribution']['positive']:.1%} | "
            f"중립={metrics['sentiment_distribution']['neutral']:.1%} | "
            f"부정={metrics['sentiment_distribution']['negative']:.1%}\n"
            f"  sentiment_score        : {metrics['sentiment_score']:+.3f}\n"
            f"  bullish_keywords       : {metrics['bullish_keywords']}\n"
            f"  bearish_keywords       : {metrics['bearish_keywords']}\n"
            f"  topics                 : {metrics['topics']}\n"
            f"  volume                 : {metrics['volume']}건"
        )
        return metrics

    # ── 뉴스 이벤트 분류 ─────────────────────────────────────────────────────

    async def analyze_news(
        self,
        news_items: list[dict],
        company: Optional[str] = None,
    ) -> NewsSignalMetrics:
        """
        뉴스 기사 리스트로부터 긍정·부정 이벤트 및 키워드를 산출한다.

        Returns:
            NewsSignalMetrics — 빈 입력 시 빈 이벤트·키워드 반환.
        Raises:
            Exception — LLM 호출 실패 또는 JSON 파싱 오류 시 그대로 전파.
        """
        if not news_items:
            print("[SignalAnalyzer][뉴스] 입력 기사 0건 → 기본 지표 반환")
            return _empty_news_metrics()

        company_label = company or "주식"
        articles = news_items[:_MAX_NEWS_ITEMS]

        article_lines: list[str] = []
        for i, item in enumerate(articles):
            text = (item.get("summary_text") or item.get("title", "")).strip()
            if text:
                article_lines.append(f"{i + 1}. {text[:_MAX_NEWS_CHARS]}")

        if not article_lines:
            print("[SignalAnalyzer][뉴스] 유효한 텍스트 없음 → 기본 지표 반환")
            return _empty_news_metrics()

        print(
            f"[SignalAnalyzer][뉴스] 이벤트 분석 시작 "
            f"| 기사={len(article_lines)}건 | company={company_label!r}"
        )
        t0 = time.monotonic()

        system_prompt = (
            "당신은 한국 주식 투자 뉴스 분석 전문가입니다. "
            "반드시 JSON만 응답하고 마크다운·코드블록은 사용하지 마세요."
        )
        user_prompt = f"""다음은 [{company_label}] 관련 뉴스 {len(article_lines)}건입니다.

{chr(10).join(article_lines)}

아래 JSON 형식으로만 응답하세요:
{{
  "positive_events": [
    {{"event": "이벤트 요약 (1~2문장)", "impact": "high|medium|low"}}
  ],
  "negative_events": [
    {{"event": "이벤트 요약 (1~2문장)", "impact": "high|medium|low"}}
  ],
  "keywords": ["키워드1", "키워드2", ...]
}}

기준:
- positive_events: 수주, 실적 개선, 정부 지원, 신사업, 수출 증가 등 긍정적 이벤트 (최대 5개)
  → 명백한 긍정 뉴스가 없어도 중립 이상의 정보가 있으면 low impact 로 포함하세요.
- negative_events: 실적 악화, 소송, 규제, 원가 상승, 수요 감소 등 부정적 이벤트 (최대 5개)
  → 명백한 부정 뉴스가 없어도 리스크 요소가 있으면 low impact 로 포함하세요.
- impact: high(직접적·즉각적 영향), medium(간접적 영향), low(미미하거나 간접적 언급)
- keywords: 뉴스 전체에서 투자 관련 핵심 키워드 TOP 10
- 모든 기사에 투자 관련 이벤트가 없더라도 최소 1개 이상의 이벤트를 추출하려고 노력하세요."""

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        elapsed = time.monotonic() - t0
        raw = response.content.strip()
        print(f"[SignalAnalyzer][뉴스] LLM 응답 수신 | 소요={elapsed:.2f}s | 길이={len(raw)}자")

        data = json.loads(raw)

        def _parse_events(raw_list: list) -> list[NewsEvent]:
            result: list[NewsEvent] = []
            for e in raw_list[:5]:
                if isinstance(e, dict) and "event" in e:
                    result.append(
                        NewsEvent(
                            event=str(e.get("event", "")),
                            impact=str(e.get("impact", "medium")),
                        )
                    )
            return result

        metrics = NewsSignalMetrics(
            positive_events=_parse_events(data.get("positive_events", [])),
            negative_events=_parse_events(data.get("negative_events", [])),
            keywords=list(data.get("keywords", []))[:10],
        )

        print(
            f"[SignalAnalyzer][뉴스] 지표 산출 완료\n"
            f"  positive_events : {len(metrics['positive_events'])}건 → "
            f"{[e['event'][:30] for e in metrics['positive_events']]}\n"
            f"  negative_events : {len(metrics['negative_events'])}건 → "
            f"{[e['event'][:30] for e in metrics['negative_events']]}\n"
            f"  keywords        : {metrics['keywords']}"
        )
        return metrics
