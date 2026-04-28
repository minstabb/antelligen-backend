"""
SNS 게시물 도메인 엔티티
=========================
순수 비즈니스 객체. ORM/DB와 분리되어 있어서 테스트하기 쉽고
infrastructure 레이어 없어도 도메인 로직 동작 가능하게.

DDD 헥사고날 아키텍처에서 application 레이어가 다루는 객체.
infrastructure(ORM)와는 Mapper로 변환한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SnsPost:
    """SNS 플랫폼에서 수집한 게시물 1건"""

    # 출처
    platform: str           # "reddit", "naver_finance", "toss_community", ...
    post_id: str            # 플랫폼 자체 ID
    post_hash: str          # sha256(platform + post_id)

    # 종목
    ticker: str             # 검색에 쓴 티커 (005930, AAPL 등)

    # 본문
    content: str            # 감정분석 대상 텍스트
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None

    # 메타
    score: Optional[int] = None         # 플랫폼 자체 점수 (upvote 등)
    comment_count: Optional[int] = None
    extra_meta: Optional[str] = None    # JSON 문자열

    # 시각
    posted_at: Optional[datetime] = None
    collected_at: datetime = field(default_factory=datetime.utcnow)

    # ID는 DB 저장 후에만 부여됨 (저장 전엔 None)
    id: Optional[int] = None

    def is_high_engagement(self) -> bool:
        """참여도 높은 게시물인지 판단 (가중치 계산에 활용)"""
        if self.score is None:
            return False
        # 플랫폼별 임계값 다름. 일단 보수적으로
        if self.platform == "reddit":
            return self.score >= 50
        if self.platform == "naver_finance":
            return self.score >= 10
        return self.score >= 20
