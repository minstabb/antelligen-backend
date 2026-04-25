"""
YouTube 댓글 감성 분석 어댑터.

수집된 YouTube 댓글 리스트를 LLM에 일괄 전달하여
투자 심리 지표(YoutubeSentimentMetrics)를 산출한다.

설계 원칙:
- 단일 LLM 호출로 50~250건 댓글을 처리해 10초 이내 완료를 목표로 한다.
- 토큰 한계를 초과하지 않도록 최대 _MAX_COMMENTS_FOR_LLM 건만 샘플링한다.
- 분석 실패 시 empty_youtube_sentiment()를 반환해 상위 호출부가 처리할 수 있게 한다.
"""

import json
from typing import Any

from langchain_openai import ChatOpenAI

from app.domains.investment.domain.value_object.youtube_sentiment_metrics import (
    YoutubeSentimentMetrics,
    empty_youtube_sentiment,
)

# LLM에 전달할 최대 댓글 수 (토큰 절약)
_MAX_COMMENTS_FOR_LLM: int = 150
# 긍/부정 키워드 최대 반환 수
_TOP_N_KEYWORDS: int = 10
# 주요 화제 최대 반환 수
_TOP_N_TOPICS: int = 5


class YoutubeSentimentAnalyzer:
    """LLM 기반 YouTube 댓글 감성 분석기."""

    def __init__(self, llm: ChatOpenAI) -> None:
        self._llm = llm

    async def analyze(
        self,
        comments: list[dict[str, Any]],
        company: str,
        top_n: int = _TOP_N_KEYWORDS,
    ) -> YoutubeSentimentMetrics:
        """
        댓글 리스트에서 투자 심리 지표를 산출한다.

        Args:
            comments: {"text": str, "author": str, ...} 형태의 댓글 목록
            company:  분석 대상 종목명 (컨텍스트 제공용)
            top_n:    반환할 키워드 최대 수

        Returns:
            YoutubeSentimentMetrics — 분석 실패 시 empty_youtube_sentiment()
        """
        texts = [
            c["text"]
            for c in comments
            if isinstance(c, dict) and c.get("text") and str(c["text"]).strip()
        ]
        volume = len(texts)

        print(f"[SentimentAnalyzer][유튜브] 분석 시작 | company={company!r} | 전체 댓글={volume}건")

        if volume == 0:
            print("[SentimentAnalyzer][유튜브] 댓글 없음 — 빈 결과 반환")
            return empty_youtube_sentiment(volume=0)

        # 토큰 한계 대응: 최대 _MAX_COMMENTS_FOR_LLM 건 샘플링
        sample = texts[:_MAX_COMMENTS_FOR_LLM]
        comments_block = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(sample))
        sample_note = (
            f"(전체 {volume}건 중 상위 {len(sample)}건 샘플)"
            if volume > _MAX_COMMENTS_FOR_LLM
            else f"(전체 {volume}건)"
        )

        system_prompt = (
            "당신은 투자 심리 분석 전문가입니다.\n"
            "주어진 YouTube 댓글들을 투자 관점에서 감성 분석하세요.\n"
            "반드시 아래 JSON 형식으로만 응답하세요 (마크다운·코드블록 금지):\n"
            "{\n"
            '  "sentiment_distribution": {\n'
            '    "positive": 긍정 비율(0.0~1.0),\n'
            '    "neutral": 중립 비율(0.0~1.0),\n'
            '    "negative": 부정 비율(0.0~1.0)\n'
            "  },\n"
            f'  "bullish_keywords": ["긍정 댓글에 자주 등장하는 투자 키워드 TOP {top_n}"],\n'
            f'  "bearish_keywords": ["부정 댓글에 자주 등장하는 투자 키워드 TOP {top_n}"],\n'
            f'  "topics": ["주요 화제 TOP {_TOP_N_TOPICS}"]\n'
            "}\n"
            "※ sentiment_distribution 세 값의 합은 반드시 1.0이어야 합니다."
        )

        user_prompt = (
            f"종목: {company}\n"
            f"분석 대상 댓글 {sample_note}:\n\n"
            f"{comments_block}\n\n"
            "위 댓글들을 투자 관점에서 감성 분석하고 JSON으로 응답하세요."
        )

        response = await self._llm.ainvoke([
            ("system", system_prompt),
            ("human", user_prompt),
        ])

        raw = response.content.strip()
        print(f"[SentimentAnalyzer][유튜브] LLM 응답 수신 | 길이={len(raw)}자")

        try:
            data = json.loads(raw)
            dist = data.get("sentiment_distribution", {})
            positive = float(dist.get("positive", 0.0))
            neutral = float(dist.get("neutral", 0.0))
            negative = float(dist.get("negative", 0.0))

            # 합계 정규화 (LLM 응답이 정확히 1.0이 아닐 수 있음)
            total = positive + neutral + negative
            if total > 0:
                positive /= total
                neutral /= total
                negative /= total
            else:
                positive = neutral = negative = 1 / 3

            sentiment_score = round(positive - negative, 4)  # -1 ~ +1

            metrics: YoutubeSentimentMetrics = {
                "sentiment_distribution": {
                    "positive": round(positive, 4),
                    "neutral": round(neutral, 4),
                    "negative": round(negative, 4),
                },
                "sentiment_score": sentiment_score,
                "bullish_keywords": list(data.get("bullish_keywords", []))[:top_n],
                "bearish_keywords": list(data.get("bearish_keywords", []))[:top_n],
                "topics": list(data.get("topics", []))[:_TOP_N_TOPICS],
                "volume": volume,
            }

            # ── 결과 출력 ───────────────────────────────────────────────────────
            dist_out = metrics["sentiment_distribution"]
            print("[SentimentAnalyzer][유튜브] ✓ 분석 완료")
            print(
                f"  sentiment_distribution → "
                f"긍정={dist_out['positive']:.1%} | "
                f"중립={dist_out['neutral']:.1%} | "
                f"부정={dist_out['negative']:.1%}"
            )
            print(f"  sentiment_score        → {sentiment_score:+.4f}  (-1=매우부정, +1=매우긍정)")
            print(f"  bullish_keywords       → {metrics['bullish_keywords']}")
            print(f"  bearish_keywords       → {metrics['bearish_keywords']}")
            print(f"  topics                 → {metrics['topics']}")
            print(f"  volume                 → {volume}건 (샘플 {len(sample)}건 분석)")

            return metrics

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"[SentimentAnalyzer][유튜브] JSON 파싱 실패: {exc!r} — 빈 결과 반환")
            return empty_youtube_sentiment(volume=volume)
