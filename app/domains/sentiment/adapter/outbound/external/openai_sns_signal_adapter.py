"""
OpenAI SNS 감정분석 Adapter
============================
SnsSignalAnalysisPort 구현체. SnsPost 묶음을 GPT에 던져서 SnsSignalResult 반환.

OpenAINewsSignalAdapter와 동일 스타일 (api_key 주입, AsyncOpenAI 인스턴스화).

모델: gpt-4o-mini (비용 효율, 감정분석 정확도 충분)
배치: 한 호출에 최대 30개 게시물 (토큰 절약)
포맷: response_format json_object 모드

밈 티커 가중치 (sector_weight_applied):
    TSLA, GME, AMC, PLTR, NVDA → 미장 밈 주식
    신뢰도(confidence) ×1.25~1.5 적용 후 1.0 클리핑
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Optional

from openai import AsyncOpenAI

from app.domains.sentiment.application.port.sns_signal_analysis_port import SnsSignalAnalysisPort
from app.domains.sentiment.application.response.analyze_sns_signal_response import (
    PlatformSignal,
    SnsEvidence,
    SnsSignalResult,
)
from app.domains.sentiment.domain.entity.sns_post import SnsPost

logger = logging.getLogger(__name__)

# 밈 티커 — SNS 신뢰도 가중치 부스트 대상
_MEME_TICKERS: set[str] = {"TSLA", "GME", "AMC", "PLTR", "NVDA"}
_MEME_BOOST = 1.35  # 신뢰도 배수 (1.25~1.5 중간값)

# 한 GPT 호출당 최대 게시물 수 (토큰 절약)
_BATCH_SIZE = 30

_SYSTEM_PROMPT = """당신은 SNS 게시물 기반 주식 투자 감정 분석 전문가입니다.
Reddit, 네이버 종목토론 등 SNS에서 수집된 게시물을 보고 종합적인 투자 감정을 분석합니다.

분석 지침:
1. 개인 의견·루머·과장 표현이 많으므로, 구체적 근거 없는 극단적 감정은 가중치를 낮추세요.
2. 업보트 수(score)가 높은 게시물일수록 커뮤니티 공감도가 높다는 의미입니다.
3. 긍정·부정이 혼재하거나 샘플이 적으면 neutral/낮은 confidence로 반환하세요.
4. evidence_highlights: 판단 근거가 된 대표 문장을 최대 5개 추출하세요.
   각 항목은 {"text": "...", "sentiment": "positive|negative|neutral", "score": 0.0~1.0, "platform": "...", "url": "..."} 형식.
5. per_platform: 플랫폼별로 집계하세요.
   각 항목: {"platform": "...", "signal": "bullish|bearish|neutral", "confidence": 0.0~1.0,
             "sample_size": N, "positive_ratio": 0.0~1.0, "negative_ratio": 0.0~1.0, "neutral_ratio": 0.0~1.0}
6. reasoning: 한국어로 한두 문장 요약. 시연 시 사용자에게 표시됩니다.

반드시 아래 JSON 형식으로만 응답하세요 (마크다운, 추가 설명 금지):
{
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <float 0.0~1.0>,
  "overall_positive_ratio": <float>,
  "overall_negative_ratio": <float>,
  "overall_neutral_ratio": <float>,
  "reasoning": "<한국어 한두 문장>",
  "per_platform": [...],
  "evidence_highlights": [...]
}"""


class OpenAISnsSignalAdapter(SnsSignalAnalysisPort):
    """SNS 감정분석 — gpt-5-mini 기반"""

    def __init__(self, api_key: str, model: str = "gpt-5-mini"):
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def analyze(
        self,
        ticker: str,
        company_name: str,
        posts: list[SnsPost],
    ) -> SnsSignalResult:
        """
        게시물 리스트 → 종합 감정 시그널.
        빈 posts면 neutral/0 즉시 반환.
        """
        if not posts:
            return SnsSignalResult(
                ticker=ticker,
                signal="neutral",
                confidence=0.0,
                total_sample_size=0,
            )

        start_ms = time.monotonic()

        # 배치 처리: 30개씩 잘라서 호출 후 결과 병합
        # MVP에서는 단일 호출 (posts가 30개 초과해도 앞 30개만 사용)
        batch = posts[:_BATCH_SIZE]
        user_message = self._format_posts(ticker, company_name, batch)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"GPT SNS 분석 JSON 파싱 실패: {e}")
            return SnsSignalResult(ticker=ticker, signal="neutral", confidence=0.0,
                                   total_sample_size=len(batch), reasoning="GPT 응답 파싱 실패")
        except Exception as e:
            logger.error(f"GPT SNS 분석 오류: {e}")
            return SnsSignalResult(ticker=ticker, signal="neutral", confidence=0.0,
                                   total_sample_size=len(batch), reasoning=f"GPT 호출 오류: {str(e)}")

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        # ─── confidence 추출 + 밈 티커 가중치 ───
        raw_confidence = float(data.get("confidence", 0.5))
        is_meme = ticker.upper() in _MEME_TICKERS
        if is_meme:
            boosted_confidence = min(1.0, raw_confidence * _MEME_BOOST)
        else:
            boosted_confidence = raw_confidence

        # ─── per_platform 파싱 ───
        per_platform: list[PlatformSignal] = []
        for p in data.get("per_platform", []):
            try:
                per_platform.append(PlatformSignal(
                    platform=p["platform"],
                    signal=p["signal"],
                    confidence=float(p.get("confidence", 0.5)),
                    sample_size=int(p.get("sample_size", 0)),
                    positive_ratio=float(p.get("positive_ratio", 0.0)),
                    negative_ratio=float(p.get("negative_ratio", 0.0)),
                    neutral_ratio=float(p.get("neutral_ratio", 0.0)),
                ))
            except (KeyError, ValueError) as e:
                logger.warning(f"per_platform 파싱 스킵: {e}")

        # ─── evidence 파싱 (최대 5개) ───
        evidence: list[SnsEvidence] = []
        for ev in data.get("evidence_highlights", [])[:5]:
            try:
                evidence.append(SnsEvidence(
                    text=ev["text"],
                    sentiment=ev["sentiment"],
                    score=float(ev.get("score", 0.5)),
                    platform=ev.get("platform", "unknown"),
                    url=ev.get("url"),
                ))
            except (KeyError, ValueError) as e:
                logger.warning(f"evidence 파싱 스킵: {e}")

        return SnsSignalResult(
            ticker=ticker,
            signal=data.get("signal", "neutral"),
            confidence=boosted_confidence,
            source_tier="하",           # SNS 기본 티어
            sector_weight_applied=is_meme,
            overall_negative_ratio=float(data.get("overall_negative_ratio", 0.0)),
            overall_positive_ratio=float(data.get("overall_positive_ratio", 0.0)),
            overall_neutral_ratio=float(data.get("overall_neutral_ratio", 0.0)),
            total_sample_size=len(batch),
            per_platform=per_platform,
            evidence=evidence,
            reasoning=data.get("reasoning", ""),
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def _format_posts(ticker: str, company_name: str, posts: list[SnsPost]) -> str:
        """SnsPost 리스트 → GPT 입력 문자열"""
        lines = [f"[{company_name}({ticker}) SNS 게시물 {len(posts)}건]\n"]
        for i, post in enumerate(posts, 1):
            lines.append(f"{i}. [{post.platform}] {post.title or '(제목 없음)'}")
            # content는 SnsPost에서 이미 2000자로 잘린 상태
            preview = post.content[:300].replace("\n", " ")
            lines.append(f"   {preview}")
            if post.score is not None:
                lines.append(f"   score={post.score}, 댓글={post.comment_count}")
            if post.url:
                lines.append(f"   url={post.url}")
            lines.append("")
        return "\n".join(lines)
