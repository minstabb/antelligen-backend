"""
뉴스 기사 투자 신호 분석 어댑터.

수집된 뉴스 기사 리스트를 LLM에 전달하여
뉴스 신호 지표(NewsSignalMetrics)를 산출한다.

설계 원칙:
- 단일 LLM 호출로 분석을 완료해 응답 지연을 최소화한다.
- 분석 실패 시 empty_news_signal()을 반환해 상위 호출부가 처리할 수 있게 한다.
"""

import json
from typing import Any

from langchain_openai import ChatOpenAI

from app.domains.investment.domain.value_object.youtube_sentiment_metrics import (
    NewsEventItem,
    NewsSignalMetrics,
    empty_news_signal,
)

# LLM에 전달할 최대 기사 수
_MAX_ARTICLES_FOR_LLM: int = 10
# 기사당 본문 preview 최대 길이 (토큰 절약)
_ARTICLE_PREVIEW_LEN: int = 200
# 반환할 키워드 최대 수
_TOP_N_KEYWORDS: int = 10
_VALID_IMPACTS = {"high", "medium", "low"}


class NewsSignalAnalyzer:
    """LLM 기반 뉴스 기사 투자 신호 분석기."""

    def __init__(self, llm: ChatOpenAI) -> None:
        self._llm = llm

    async def analyze(
        self,
        articles: list[dict[str, Any]],
        company: str,
    ) -> NewsSignalMetrics:
        """
        뉴스 기사 리스트에서 투자 신호 지표를 산출한다.

        Args:
            articles: {"title": str, "source": str, "summary_text": str, ...} 형태의 기사 목록
            company:  분석 대상 종목명

        Returns:
            NewsSignalMetrics — 분석 실패 시 empty_news_signal()
        """
        valid = [
            a for a in articles
            if isinstance(a, dict) and (a.get("title") or a.get("summary_text"))
        ]
        print(f"[SignalAnalyzer][뉴스] 분석 시작 | company={company!r} | 유효 기사={len(valid)}건")

        if not valid:
            print("[SignalAnalyzer][뉴스] 기사 없음 — 빈 결과 반환")
            return empty_news_signal()

        sample = valid[:_MAX_ARTICLES_FOR_LLM]
        articles_block = "\n".join(
            (
                f"{i + 1}. [{a.get('source', '출처미상')}] {a.get('title', '(제목없음)')}\n"
                f"   {str(a.get('summary_text') or a.get('snippet', ''))[:_ARTICLE_PREVIEW_LEN]}"
            )
            for i, a in enumerate(sample)
        )

        system_prompt = (
            "당신은 투자 신호 분석 전문가입니다.\n"
            "주어진 뉴스 기사들을 투자 관점에서 분석하여 긍·부정 이벤트와 핵심 키워드를 추출하세요.\n"
            "반드시 아래 JSON 형식으로만 응답하세요 (마크다운·코드블록 금지):\n"
            "{\n"
            '  "positive_events": [\n'
            '    {"event": "이벤트 설명 1문장", "impact": "high|medium|low"}\n'
            "  ],\n"
            '  "negative_events": [\n'
            '    {"event": "이벤트 설명 1문장", "impact": "high|medium|low"}\n'
            "  ],\n"
            f'  "keywords": ["핵심 투자 키워드 TOP {_TOP_N_KEYWORDS}"]\n'
            "}\n"
            "impact 기준: high=주가에 즉각적 영향, medium=중기 영향, low=간접적 영향"
        )

        user_prompt = (
            f"종목: {company}\n"
            f"분석 대상 뉴스 {len(sample)}건 (전체 {len(valid)}건 중):\n\n"
            f"{articles_block}\n\n"
            "위 뉴스들을 투자 관점에서 분석하고 JSON으로 응답하세요."
        )

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        raw = response.content.strip()
        print(f"[SignalAnalyzer][뉴스] LLM 응답 수신 | 길이={len(raw)}자")

        try:
            data = json.loads(raw)

            def _parse_events(items: Any) -> list[NewsEventItem]:
                if not isinstance(items, list):
                    return []
                result: list[NewsEventItem] = []
                for item in items:
                    if not isinstance(item, dict) or "event" not in item:
                        continue
                    impact = str(item.get("impact", "medium")).lower()
                    if impact not in _VALID_IMPACTS:
                        impact = "medium"
                    result.append({
                        "event": str(item["event"]),
                        "impact": impact,
                    })
                return result

            metrics: NewsSignalMetrics = {
                "positive_events": _parse_events(data.get("positive_events", [])),
                "negative_events": _parse_events(data.get("negative_events", [])),
                "keywords": [str(k) for k in data.get("keywords", [])][:_TOP_N_KEYWORDS],
            }

            # ── 결과 출력 ───────────────────────────────────────────────────────
            print("[SignalAnalyzer][뉴스] ✓ 분석 완료")
            print(f"  positive_events ({len(metrics['positive_events'])}건):")
            for e in metrics["positive_events"]:
                print(f"    [{e['impact'].upper()}] {e['event']}")
            print(f"  negative_events ({len(metrics['negative_events'])}건):")
            for e in metrics["negative_events"]:
                print(f"    [{e['impact'].upper()}] {e['event']}")
            print(f"  keywords → {metrics['keywords']}")

            return metrics

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"[SignalAnalyzer][뉴스] JSON 파싱 실패: {exc!r} — 빈 결과 반환")
            return empty_news_signal()
