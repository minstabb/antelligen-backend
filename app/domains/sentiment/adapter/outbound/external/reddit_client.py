"""
Reddit Client (.json 무인증)
============================
회의록 4번 SNS 감정분석의 핵심 소스.

API 키 없이 동작 (Reddit이 공개적으로 제공하는 .json 엔드포인트 사용).
이유: 신생 Reddit 계정에서 OAuth 앱 생성이 막히는 문제 우회 + 배포 시
환경변수 관리 단순화.

엔드포인트:
    https://www.reddit.com/r/{subreddit}/search.json?q=...&restrict_sr=1

레이트리밋:
    User-Agent 박으면 분당 약 60회. 우리는 초당 1회 페이스로 보수적 운영.

확장성:
    나중에 OAuth 키 발급되면 PRAW로 교체 가능. SnsCollectorPort 인터페이스가
    동일하므로 collector 클래스만 갈아끼우면 됨. 나머지 코드 영향 X.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.domains.sentiment.application.port.sns_collector_port import SnsCollectorPort
from app.domains.sentiment.domain.entity.sns_post import SnsPost
from app.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


# 티커 종류별 검색할 서브레딧
US_SUBREDDITS = ["stocks", "investing", "wallstreetbets", "StockMarket"]
KR_SUBREDDITS = ["Korean_Stocks"]   # 규모 작음, 보조용

# Reddit이 봇 식별 가능하도록 의미 있는 UA
DEFAULT_UA = "windows:antelligen-sentiment:v0.1 (research project)"


class RedditClient(SnsCollectorPort):
    """Reddit 무인증 수집기 (.json 엔드포인트)"""

    platform = "reddit"

    def __init__(
        self,
        user_agent: Optional[str] = None,
        request_delay_seconds: float = 1.0,
        timeout_seconds: float = 10.0,
    ):
        # 우선순위: 인자 > 환경변수 > 기본값
        settings = get_settings()
        self.user_agent = (
            user_agent
            or os.getenv("REDDIT_USER_AGENT")
            or DEFAULT_UA
        )
        self.request_delay = request_delay_seconds
        self.timeout = timeout_seconds

    def is_available(self) -> bool:
        """UA만 있으면 동작 가능"""
        return bool(self.user_agent)

    async def collect(self, ticker: str, limit: int = 50) -> list[SnsPost]:
        """
        Reddit 게시물 수집.

        티커 종류 자동 판별:
        - 숫자 6자리 → 국장 → KR_SUBREDDITS
        - 그 외 (영문) → 미장 → US_SUBREDDITS

        검색 쿼리 형식:
        - 미장: "$AAPL" (Reddit에서 티커 매칭률 높음)
        - 국장: "삼성전자" 같은 회사명 (티커 코드는 매칭 안 됨)
        """
        if not self.is_available():
            logger.warning("RedditClient: User-Agent 미설정, 수집 건너뜀")
            return []

        query, subreddits = self._resolve_query(ticker)
        per_sub = max(1, limit // len(subreddits))

        all_posts: list[SnsPost] = []

        async with httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
        ) as client:
            for sub_name in subreddits:
                try:
                    posts = await self._fetch_subreddit(
                        client, sub_name, query, per_sub, ticker
                    )
                    all_posts.extend(posts)
                    # 레이트리밋 보호
                    await asyncio.sleep(self.request_delay)
                except Exception as e:
                    # 한 서브레딧 실패가 전체를 막지 않도록
                    logger.warning(f"Reddit r/{sub_name} 수집 실패: {e}")
                    continue

        logger.info(f"Reddit 수집 완료: ticker={ticker}, 총 {len(all_posts)}건")
        return all_posts

    def _resolve_query(self, ticker: str) -> tuple[str, list[str]]:
        """티커 → (검색어, 서브레딧 리스트)"""
        is_kr = ticker.isdigit()
        if is_kr:
            # 국장: 종목코드만으론 매칭 부족. 회사명이 더 잘 잡힘.
            # 단순 MVP는 ticker 그대로 (추후 회사명 매핑 추가 가능)
            return ticker, KR_SUBREDDITS
        # 미장: $ 접두사가 매칭률 높음 ("$AAPL" → "Apple stock" 등 잡힘)
        return f"${ticker}", US_SUBREDDITS

    async def _fetch_subreddit(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
        query: str,
        limit: int,
        ticker: str,
    ) -> list[SnsPost]:
        """단일 서브레딧 검색"""
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {
            "q": query,
            "restrict_sr": "1",     # 해당 서브레딧 내에서만
            "sort": "relevance",
            "t": "week",            # 최근 1주
            "limit": min(limit, 25),
        }

        resp = await client.get(url, params=params)

        # 429 Too Many Requests: 5초 대기 후 1회 재시도
        if resp.status_code == 429:
            logger.warning(f"Reddit 429, 5초 대기 후 재시도: r/{subreddit}")
            await asyncio.sleep(5)
            resp = await client.get(url, params=params)

        resp.raise_for_status()
        data = resp.json()

        posts: list[SnsPost] = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            sns_post = self._to_sns_post(post, subreddit, ticker)
            if sns_post:
                posts.append(sns_post)

        return posts

    def _to_sns_post(
        self, post: dict, subreddit: str, ticker: str
    ) -> Optional[SnsPost]:
        """Reddit API 응답 → SnsPost 변환"""
        title = post.get("title", "") or ""
        selftext = post.get("selftext", "") or ""
        text = f"{title}\n{selftext}".strip()

        # 너무 짧은 글은 분석 가치 없음
        if len(text) < 10:
            return None

        post_id = post.get("id", "")
        if not post_id:
            return None

        post_hash = self._make_hash(self.platform, post_id)

        # 추가 메타데이터 (가중치 계산에 활용)
        extra_meta = json.dumps(
            {
                "subreddit": subreddit,
                "upvote_ratio": post.get("upvote_ratio"),
                "is_self": post.get("is_self"),
            },
            ensure_ascii=False,
        )

        # 게시 시각 변환
        posted_at = None
        created_utc = post.get("created_utc")
        if created_utc:
            try:
                posted_at = datetime.fromtimestamp(created_utc, tz=timezone.utc).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        return SnsPost(
            platform=self.platform,
            post_id=post_id,
            post_hash=post_hash,
            ticker=ticker,
            title=title,
            content=text[:2000],   # 토큰 비용 제어 — GPT 입력은 충분히 길게 하되 폭주 방지
            url=f"https://reddit.com{post.get('permalink', '')}",
            author=post.get("author"),
            score=post.get("score"),
            comment_count=post.get("num_comments"),
            extra_meta=extra_meta,
            posted_at=posted_at,
        )

    @staticmethod
    def _make_hash(platform: str, post_id: str) -> str:
        """sha256(platform + post_id) - 전역 unique key"""
        raw = f"{platform}:{post_id}"
        return hashlib.sha256(raw.encode()).hexdigest()
