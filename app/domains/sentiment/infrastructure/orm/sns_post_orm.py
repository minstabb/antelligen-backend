"""
SNS 게시물 ORM
==============
회의록 4번 - 댓글/SNS 감정분석 에이전트의 데이터 저장소.

Reddit, 네이버 종목토론, 토스 주식판 등 여러 플랫폼에서 수집한 게시물을
하나의 테이블로 통일해서 저장한다. platform 컬럼으로 출처 구분.

설계 원칙:
1. 기존 collected_news_orm.py 패턴 그대로 따름 (VectorBase, sha256 url_hash)
2. platform별로 동일 url이 들어올 수 있어서 (post_id + platform) 조합으로 unique
3. ticker 컬럼으로 빠른 조회 (인덱스)
4. 분석 단계에서 sentiment 결과를 채워넣는 형태가 아니라,
   원본 게시물만 저장. 감정분석 결과는 호출 시점에 GPT로 매번 계산.
   (이유: 감정 결과가 시간에 따라 의미 없음. 캐시 가치 낮음.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.vector_database import VectorBase


class SnsPostOrm(VectorBase):
    __tablename__ = "sns_posts"

    # ─────────────────────────────────────────────
    # 기본 식별자
    # ─────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ─────────────────────────────────────────────
    # 출처 (어디서 왔는지)
    # ─────────────────────────────────────────────
    platform: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="reddit | naver_finance | toss_community | x | facebook"
    )
    post_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="플랫폼 자체 게시물 ID (예: reddit submission id, 네이버 토론글 ID)"
    )
    post_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="sha256(platform + post_id) - 중복 방지용 전역 unique key"
    )

    # ─────────────────────────────────────────────
    # 검색/필터링용
    # ─────────────────────────────────────────────
    ticker: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="검색에 사용한 종목 티커 (005930, AAPL 등). 인덱스 필수."
    )

    # ─────────────────────────────────────────────
    # 본문
    # ─────────────────────────────────────────────
    title: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="게시물 제목 (Reddit submission title 등). 댓글이면 null."
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="본문 텍스트. 감정분석의 입력. 길이 제한 X (Text)."
    )
    url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="원본 게시물 URL (있는 경우만)"
    )
    author: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="작성자 닉네임/아이디 (선택)"
    )

    # ─────────────────────────────────────────────
    # 메타 (플랫폼별 신호 — 가중치 계산에 활용)
    # ─────────────────────────────────────────────
    score: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="플랫폼 자체 점수 (Reddit upvote, 네이버 추천 수 등). 가중치 계산용."
    )
    comment_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="댓글 수 (참여도 지표)"
    )
    extra_meta: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="플랫폼별 추가 메타데이터 JSON 문자열 (subreddit 이름, 추천비율 등)"
    )

    # ─────────────────────────────────────────────
    # 시각
    # ─────────────────────────────────────────────
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="게시물이 작성된 시각 (플랫폼 기준)"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow,
        comment="수집 시각 (우리 서버 기준)"
    )

    # ─────────────────────────────────────────────
    # 인덱스/제약조건
    # ─────────────────────────────────────────────
    __table_args__ = (
        # 종목별 + 플랫폼별 빠른 조회
        Index("ix_sns_posts_ticker_platform", "ticker", "platform"),
        # 시간 정렬 빠르게
        Index("ix_sns_posts_collected_at", "collected_at"),
        # 플랫폼+게시물ID 조합도 unique (post_hash와 중복 보장이지만 안전망)
        UniqueConstraint("platform", "post_id", name="uq_sns_posts_platform_postid"),
    )

    def __repr__(self) -> str:
        return (
            f"<SnsPostOrm id={self.id} platform={self.platform} "
            f"ticker={self.ticker} score={self.score}>"
        )
