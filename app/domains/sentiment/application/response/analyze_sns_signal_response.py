"""
SNS 감정분석 응답 DTO
======================
영진님 메인 에이전트가 통합할 때 받아갈 표준 응답 형태.

회의록 4번 요구사항 + 2번 컨피던스 차등 반영:
- bullish/bearish/neutral 시그널
- confidence (0~1, 신뢰도)
- source_tier (회의록 2번 — SNS는 기본 "하", 단 엔터/게임은 가중치 부스트)
- negative_ratio (회의록 4번 — VIX와 비교용)
- platform별 분리 결과 (메인 에이전트가 가중합 가능하게)

표준 SubAgentResponse와 호환되는 구조.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


# 시그널/티어 정의 - 회의록 그대로
SignalLiteral = Literal["bullish", "bearish", "neutral"]
SourceTierLiteral = Literal["상", "중", "중하", "하"]


@dataclass
class SnsEvidence:
    """판단 근거가 된 게시물 발췌 (설명가능성 — 시연 시 핵심)"""
    text: str
    sentiment: Literal["positive", "negative", "neutral"]
    score: float       # 0.0 ~ 1.0
    platform: str
    url: Optional[str] = None


@dataclass
class PlatformSignal:
    """플랫폼별 시그널 (메인 에이전트가 가중합용으로 받아감)"""
    platform: str               # "reddit" | "naver_finance" | ...
    signal: SignalLiteral
    confidence: float           # 0.0 ~ 1.0
    sample_size: int            # 분석한 게시물 수
    positive_ratio: float
    negative_ratio: float
    neutral_ratio: float


@dataclass
class SnsSignalResult:
    """
    SNS 감정분석 최종 결과.

    영진님 메인 에이전트는 이 객체를 받아서:
    1. signal/confidence를 종합 시그널 가중합에 반영
    2. negative_ratio를 VIX와 비교 그래프에 사용
    3. evidence로 사용자에게 "왜 이런 판단을 했는지" 설명
    """

    # ─── 종합 결과 ───
    ticker: str
    signal: SignalLiteral
    confidence: float                       # 0.0 ~ 1.0
    source_tier: SourceTierLiteral = "하"   # SNS 기본 "하"
    sector_weight_applied: bool = False     # 엔터/게임/밈 가중치 적용 여부

    # ─── 회의록 4번 - VIX와 비교할 부정비율 ───
    overall_negative_ratio: float = 0.0     # 전체 게시물 중 부정 비율
    overall_positive_ratio: float = 0.0
    overall_neutral_ratio: float = 0.0

    # ─── 통계 ───
    total_sample_size: int = 0              # 모든 플랫폼 합산 샘플 수

    # ─── 플랫폼별 분리 결과 ───
    per_platform: list[PlatformSignal] = field(default_factory=list)

    # ─── 설명가능성 (Explainability) ───
    evidence: list[SnsEvidence] = field(default_factory=list)
    reasoning: str = ""                     # GPT가 작성한 한국어 종합 설명

    # ─── 메타 ───
    analyzed_at: datetime = field(default_factory=datetime.utcnow)
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        """JSON 직렬화 (라우터에서 응답할 때)"""
        return {
            "ticker": self.ticker,
            "signal": self.signal,
            "confidence": round(self.confidence, 3),
            "source_tier": self.source_tier,
            "sector_weight_applied": self.sector_weight_applied,
            "overall_negative_ratio": round(self.overall_negative_ratio, 3),
            "overall_positive_ratio": round(self.overall_positive_ratio, 3),
            "overall_neutral_ratio": round(self.overall_neutral_ratio, 3),
            "total_sample_size": self.total_sample_size,
            "per_platform": [
                {
                    "platform": p.platform,
                    "signal": p.signal,
                    "confidence": round(p.confidence, 3),
                    "sample_size": p.sample_size,
                    "positive_ratio": round(p.positive_ratio, 3),
                    "negative_ratio": round(p.negative_ratio, 3),
                    "neutral_ratio": round(p.neutral_ratio, 3),
                }
                for p in self.per_platform
            ],
            "evidence": [
                {
                    "text": e.text,
                    "sentiment": e.sentiment,
                    "score": round(e.score, 3),
                    "platform": e.platform,
                    "url": e.url,
                }
                for e in self.evidence
            ],
            "reasoning": self.reasoning,
            "analyzed_at": self.analyzed_at.isoformat(),
            "elapsed_ms": self.elapsed_ms,
        }


