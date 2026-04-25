from typing import Optional

from app.domains.news.application.port.collected_news_repository_port import CollectedNewsRepositoryPort
from app.domains.news.application.port.naver_news_search_port import NaverNewsSearchPort
from app.domains.news.application.response.collect_naver_news_response import (
    CollectNaverNewsResponse,
    CollectedNewsItemResponse,
)

COLLECTION_KEYWORDS = [
    # 지수
    "코스피", "코스닥", "코스피200", "나스닥", "다우존스",
    # 경제 일반
    "금리", "환율", "물가", "인플레이션", "경기침체", "무역", "수출", "기준금리", "GDP",
    # 섹터
    "반도체", "2차전지", "배터리", "AI", "인공지능", "바이오", "제약", "자동차",
    "조선", "방산", "에너지", "태양광", "전기차", "로봇", "금융",
    # 주요 종목
    "삼성전자", "SK하이닉스", "현대차", "네이버", "카카오", "셀트리온",
    "삼성바이오로직스", "포스코", "LG에너지솔루션", "기아", "삼성SDI",
    "KB금융", "신한지주", "하나금융", "현대모비스", "LG화학",
    # 주식 일반
    "주식", "증시", "주가", "배당", "공매도", "IPO", "상장",
]


class CollectNaverNewsUseCase:
    def __init__(
        self,
        naver_news_port: NaverNewsSearchPort,
        repository: CollectedNewsRepositoryPort,
    ):
        self._naver_news_port = naver_news_port
        self._repository = repository

    async def execute(self, keywords: Optional[list[str]] = None) -> CollectNaverNewsResponse:
        collected: list[CollectedNewsItemResponse] = []
        skipped = 0

        for keyword in (keywords or COLLECTION_KEYWORDS):
            for page in range(10):  # 100개 × 10페이지 = 키워드당 최대 1000건
                start = page * 100 + 1
                articles = await self._naver_news_port.search(keyword=keyword, display=100, start=start)
                if not articles:
                    break
                for article in articles:
                    if await self._repository.exists_by_url(article.url):
                        skipped += 1
                        continue
                    saved = await self._repository.save(article)
                    collected.append(
                        CollectedNewsItemResponse(
                            title=saved.title,
                            description=saved.description,
                            url=saved.url,
                            published_at=saved.published_at,
                            keyword=saved.keyword,
                        )
                    )

        return CollectNaverNewsResponse(
            total_collected=len(collected),
            skipped_duplicates=skipped,
            items=collected,
        )
