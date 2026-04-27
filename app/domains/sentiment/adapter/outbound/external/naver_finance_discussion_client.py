"""
Naver Finance Discussion Client (종목토론 스크래핑)
====================================================
회의록 4번 SNS 감정분석 소스 중 하나 (네이버 종목토론).

API 키 없이 동작. finance.naver.com/item/board.naver 정적 HTML 파싱.
국장 티커(6자리 숫자)만 지원. 미장 티커 들어오면 빈 리스트 반환.

엔드포인트:
    https://finance.naver.com/item/board.naver?code={종목코드}&page={페이지}

수집 정보: 제목, 작성자, 작성일, 조회수, 추천수, 반대수
본문: 상세 페이지 추가 GET 필요 → MVP에서는 제목만 사용.
TODO: 추후 상세 본문 스크래핑 추가 가능
    (board_read.naver?code={code}&nid={nid} 개별 요청)

인코딩: EUC-KR (네이버 구형 페이지)

확장성:
    나중에 모바일 API 엔드포인트 발견되면 교체 가능.
    SnsCollectorPort 인터페이스 동일 → 클래스만 갈아끼우면 됨.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup

from app.domains.sentiment.application.port.sns_collector_port import SnsCollectorPort
from app.domains.sentiment.domain.entity.sns_post import SnsPost

logger = logging.getLogger(__name__)

# 네이버 봇 차단 우회용 브라우저 UA
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BOARD_URL = "https://finance.naver.com/item/board.naver"


class NaverFinanceDiscussionClient(SnsCollectorPort):
    """네이버 종목토론 수집기 (정적 HTML 스크래핑)"""

    platform = "naver_finance"

    def __init__(
        self,
        request_delay_seconds: float = 1.0,
        timeout_seconds: float = 10.0,
    ):
        self.request_delay = request_delay_seconds
        self.timeout = timeout_seconds
        self.user_agent = _DEFAULT_UA

    def is_available(self) -> bool:
        """API 키 불필요 — 항상 사용 가능"""
        return True

    async def collect(self, ticker: str, limit: int = 50) -> list[SnsPost]:
        """
        네이버 종목토론 게시물 수집.

        국장 티커(6자리 숫자)만 지원.
        미장 티커(영문) 들어오면 빈 리스트 반환.
        """
        if not ticker.isdigit():
            logger.debug(f"NaverFinanceDiscussionClient: 미장 티커 skip: {ticker}")
            return []

        all_posts: list[SnsPost] = []
        page = 1

        async with httpx.AsyncClient(
            headers={
                "User-Agent": self.user_agent,
                "Referer": "https://finance.naver.com/",
            },
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:
            while len(all_posts) < limit:
                try:
                    page_posts = await self._fetch_page(client, ticker, page)
                except Exception as e:
                    logger.warning(f"Naver 종목토론 페이지 {page} 수집 실패: {e}")
                    break

                if not page_posts:
                    break

                all_posts.extend(page_posts)
                page += 1
                await asyncio.sleep(self.request_delay)

        result = all_posts[:limit]
        logger.info(f"Naver 종목토론 수집 완료: ticker={ticker}, 총 {len(result)}건")
        return result

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        ticker: str,
        page: int,
    ) -> list[SnsPost]:
        """단일 페이지 스크래핑"""
        params = {"code": ticker, "page": page}
        resp = await client.get(_BOARD_URL, params=params)

        # 429 Too Many Requests: 5초 대기 후 1회 재시도
        if resp.status_code == 429:
            logger.warning(f"Naver 429, 5초 대기 후 재시도: ticker={ticker} page={page}")
            await asyncio.sleep(5)
            resp = await client.get(_BOARD_URL, params=params)

        resp.raise_for_status()

        # 네이버 구형 페이지 — EUC-KR 디코딩
        content = resp.content.decode("euc-kr", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        return self._parse_board_table(soup, ticker)

    def _parse_board_table(self, soup: BeautifulSoup, ticker: str) -> list[SnsPost]:
        """HTML → SnsPost 리스트 변환"""
        table = soup.find("table", class_="type2")
        if not table:
            return []

        posts: list[SnsPost] = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")

            post = self._parse_row(tds, ticker)
            if post:
                posts.append(post)

        return posts

    def _parse_row(self, tds, ticker: str) -> Optional[SnsPost]:
        """TR → SnsPost 변환
        실제 컬럼 구조 (6컬럼):
          [0] 작성일 | [1] 제목 | [2] 작성자 | [3] 조회 | [4] 추천 | [5] 반대
        """
        if len(tds) < 6:
            return None

        title_td = tds[1]
        a_tag = title_td.find("a")
        if not a_tag:
            return None

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 2:
            return None

        # nid 추출: href = /item/board_read.naver?code=005930&nid=12345
        href = a_tag.get("href", "")
        nid = self._extract_nid(href)
        if not nid:
            return None

        # 추가 컬럼 파싱
        date_str = tds[0].get_text(strip=True)
        author = tds[2].get_text(strip=True)
        views_str = tds[3].get_text(strip=True)
        likes_str = tds[4].get_text(strip=True)
        dislikes_str = tds[5].get_text(strip=True)

        views = self._parse_int(views_str)
        likes = self._parse_int(likes_str)
        dislikes = self._parse_int(dislikes_str)
        posted_at = self._parse_date(date_str)

        post_hash = self._make_hash(self.platform, nid)
        extra_meta = json.dumps(
            {"opposed": dislikes, "views": views},
            ensure_ascii=False,
        )

        return SnsPost(
            platform=self.platform,
            post_id=nid,
            post_hash=post_hash,
            ticker=ticker,
            title=title,
            content=title,   # TODO: 추후 상세 본문 스크래핑 추가 가능
            url=f"https://finance.naver.com{href}",
            author=author,
            score=likes,
            comment_count=None,
            extra_meta=extra_meta,
            posted_at=posted_at,
        )

    @staticmethod
    def _extract_nid(href: str) -> Optional[str]:
        """href에서 nid 파라미터 추출"""
        if "nid=" not in href:
            return None
        try:
            qs = parse_qs(href.split("?", 1)[-1])
            nid_list = qs.get("nid", [])
            return nid_list[0] if nid_list else None
        except Exception:
            return None

    @staticmethod
    def _parse_int(text: str) -> int:
        """숫자 텍스트 → int (실패 시 0)"""
        try:
            return int(text.replace(",", "").strip())
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
        """네이버 날짜 형식 파싱: '2024.01.01 12:00' 또는 '01.01 12:00'"""
        if not date_str:
            return None
        for fmt in ("%Y.%m.%d %H:%M", "%m.%d %H:%M"):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                # 연도 없는 포맷이면 현재 연도 주입
                if fmt == "%m.%d %H:%M":
                    dt = dt.replace(year=datetime.utcnow().year)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def _make_hash(platform: str, post_id: str) -> str:
        """sha256(platform + post_id) — 전역 unique key"""
        raw = f"{platform}:{post_id}"
        return hashlib.sha256(raw.encode()).hexdigest()
