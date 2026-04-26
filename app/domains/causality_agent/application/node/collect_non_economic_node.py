import asyncio
import logging
from typing import Any, Dict, List

from app.domains.causality_agent.adapter.outbound.external.finnhub_news_client import (
    FinnhubNewsClient,
)
from app.domains.causality_agent.adapter.outbound.external.gdelt_client import GdeltClient
from app.domains.causality_agent.adapter.outbound.external.gpr_index_client import GprIndexClient
from app.domains.causality_agent.adapter.outbound.external.naver_korean_news_client import (
    NaverKoreanNewsClient,
)
from app.domains.causality_agent.adapter.outbound.external.related_assets_client import (
    RelatedAssetsClient,
)
from app.domains.causality_agent.adapter.outbound.external.yahoo_finance_news_client import (
    YahooFinanceNewsClient,
)
from app.domains.causality_agent.domain.state.causality_agent_state import CausalityAgentState
from app.domains.stock.domain.service.market_region_resolver import MarketRegionResolver
from app.infrastructure.external.korean_company_directory import lookup_korean_name

logger = logging.getLogger(__name__)

# 지수(Index) 티커 → GDELT 검색용 자연어 키워드
# Finnhub /company-news는 지수를 지원하지 않아 스킵하고,
# GDELT/yfinance는 일반 용어로 검색하면 히트율이 높다.
_INDEX_KEYWORD_MAP: Dict[str, str] = {
    "IXIC": "NASDAQ Composite",
    "^IXIC": "NASDAQ Composite",
    "GSPC": "S&P 500",
    "^GSPC": "S&P 500",
    "SPX": "S&P 500",
    "DJI": "Dow Jones",
    "^DJI": "Dow Jones",
    "RUT": "Russell 2000",
    "^RUT": "Russell 2000",
    "VIX": "VIX volatility",
    "^VIX": "VIX volatility",
}


def _is_index_ticker(ticker: str) -> bool:
    return ticker.startswith("^") or ticker.upper() in _INDEX_KEYWORD_MAP


def _gdelt_keyword(ticker: str) -> str:
    return _INDEX_KEYWORD_MAP.get(ticker.upper(), ticker)


async def _collect_news(ticker: str, start_date, end_date) -> List[Dict[str, Any]]:
    """뉴스 소스를 ticker 종류에 따라 분기 호출.

    - 한국 종목(005930 / 005930.KS / 005930.KQ): Naver(주) + GDELT 한글 키워드(보조). Finnhub 한국 종목 미지원.
    - 지수(IXIC/^GSPC): Finnhub 스킵, GDELT 자연어 키워드.
    - 그 외(미국 개별 종목 등): Finnhub + GDELT 병렬, 모두 비면 yfinance fallback.
    """
    region = MarketRegionResolver.resolve(ticker)
    if region.is_korea():
        return await _collect_news_korean(ticker, start_date, end_date)

    is_index = _is_index_ticker(ticker)
    gdelt_keyword = _gdelt_keyword(ticker)

    if is_index:
        logger.info(
            "[CausalityAgent] 지수 티커(%s) 감지 → Finnhub 스킵, GDELT 키워드='%s'",
            ticker, gdelt_keyword,
        )
        finnhub_result: Any = []
        gdelt_result = await asyncio.gather(
            GdeltClient().fetch_articles(gdelt_keyword, start_date, end_date),
            return_exceptions=True,
        )
        gdelt_result = gdelt_result[0]
    else:
        finnhub_result, gdelt_result = await asyncio.gather(
            FinnhubNewsClient().fetch_articles(ticker, start_date, end_date),
            GdeltClient().fetch_articles(gdelt_keyword, start_date, end_date),
            return_exceptions=True,
        )

    articles: List[Dict[str, Any]] = []
    finnhub_count = 0
    gdelt_count = 0

    if isinstance(finnhub_result, list):
        articles.extend(finnhub_result)
        finnhub_count = len(finnhub_result)
    elif isinstance(finnhub_result, Exception):
        logger.warning("[CausalityAgent] Finnhub 예외: %s", finnhub_result)

    if isinstance(gdelt_result, list):
        articles.extend(gdelt_result)
        gdelt_count = len(gdelt_result)
    elif isinstance(gdelt_result, Exception):
        logger.warning("[CausalityAgent] GDELT 예외: %s", gdelt_result)

    yf_count = 0
    if not articles:
        logger.info("[CausalityAgent] Finnhub/GDELT 모두 0건 → yfinance fallback")
        try:
            yf_articles = await YahooFinanceNewsClient().fetch_articles(
                ticker, start_date, end_date
            )
            articles.extend(yf_articles)
            yf_count = len(yf_articles)
        except Exception as exc:
            logger.warning("[CausalityAgent] yfinance news 예외: %s", exc)

    logger.info(
        "[CausalityAgent]   └ 뉴스 소스: finnhub=%d, gdelt=%d, yfinance=%d",
        finnhub_count, gdelt_count, yf_count,
    )
    return articles


async def _collect_news_korean(ticker: str, start_date, end_date) -> List[Dict[str, Any]]:
    """한국 종목 전용: Naver(주) + GDELT(한글 회사명 키워드, 보조) 병렬."""
    korean_name = lookup_korean_name(ticker)
    gdelt_keyword = korean_name or ticker.upper().split(".")[0]

    logger.info(
        "[CausalityAgent] 한국 종목(%s) 감지 → Naver 주 소스 + GDELT 보조 (키워드='%s')",
        ticker, gdelt_keyword,
    )

    naver_result, gdelt_result = await asyncio.gather(
        NaverKoreanNewsClient().fetch_articles(ticker, start_date, end_date),
        GdeltClient().fetch_articles(gdelt_keyword, start_date, end_date),
        return_exceptions=True,
    )

    articles: List[Dict[str, Any]] = []
    naver_count = 0
    gdelt_count = 0

    if isinstance(naver_result, list):
        articles.extend(naver_result)
        naver_count = len(naver_result)
    elif isinstance(naver_result, Exception):
        logger.warning("[CausalityAgent] Naver(KR) 예외: %s", naver_result)

    if isinstance(gdelt_result, list):
        articles.extend(gdelt_result)
        gdelt_count = len(gdelt_result)
    elif isinstance(gdelt_result, Exception):
        logger.warning("[CausalityAgent] GDELT(KR) 예외: %s", gdelt_result)

    logger.info(
        "[CausalityAgent]   └ 뉴스 소스: naver=%d, gdelt=%d",
        naver_count, gdelt_count,
    )
    return articles


async def collect_non_economic(state: CausalityAgentState) -> Dict[str, Any]:
    """VIX·원유·금·미국채·엔화 + 뉴스(Finnhub/GDELT/yfinance) + GPR 을 병렬로 수집한다."""
    ticker = state["ticker"]
    start_date = state["start_date"]
    end_date = state["end_date"]
    errors: list = list(state.get("errors", []))

    logger.info("[CausalityAgent] [2/3] 연관자산 + 뉴스 + GPR 수집 시작")
    related_task = RelatedAssetsClient().fetch(start_date, end_date)
    news_task = _collect_news(ticker, start_date, end_date)
    gpr_task = GprIndexClient().fetch(start_date, end_date)

    related_result, news_result, gpr_result = await asyncio.gather(
        related_task, news_task, gpr_task, return_exceptions=True
    )

    related_assets: list = []
    if isinstance(related_result, Exception):
        msg = f"연관자산 수집 실패: {related_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        related_assets = related_result

    news_articles: list = []
    if isinstance(news_result, Exception):
        msg = f"뉴스 수집 실패: {news_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        news_articles = news_result

    gpr_observations: list = []
    if isinstance(gpr_result, Exception):
        msg = f"GPR 수집 실패: {gpr_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        gpr_observations = gpr_result

    logger.info(
        "[CausalityAgent] [2/3] 완료: assets=%d, news=%d, gpr=%d",
        len(related_assets),
        len(news_articles),
        len(gpr_observations),
    )
    return {
        "related_assets": related_assets,
        "news_articles": news_articles,
        "gpr_observations": gpr_observations,
        "errors": errors,
    }
