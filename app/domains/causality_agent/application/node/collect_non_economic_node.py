import asyncio
import logging
from typing import Any, Dict, List

from app.domains.causality_agent.adapter.outbound.external.finnhub_news_client import (
    FinnhubNewsClient,
)
from app.domains.causality_agent.adapter.outbound.external.gdelt_client import GdeltClient
from app.domains.causality_agent.adapter.outbound.external.gpr_index_client import GprIndexClient
from app.domains.causality_agent.adapter.outbound.external.market_benchmark_client import (
    MarketBenchmarkClient,
)
from app.domains.causality_agent.adapter.outbound.external.naver_korean_news_client import (
    NaverKoreanNewsClient,
)
from app.domains.causality_agent.adapter.outbound.external.related_assets_client import (
    RelatedAssetsClient,
)
from app.domains.causality_agent.adapter.outbound.external.sector_benchmark_client import (
    SectorBenchmarkClient,
)
from app.domains.causality_agent.adapter.outbound.external.yahoo_finance_news_client import (
    YahooFinanceNewsClient,
)
from app.domains.causality_agent.domain.state.causality_agent_state import CausalityAgentState
# SEC EDGAR client는 dashboard 도메인에 위치 (history_agent 도 같은 패턴으로 재사용 중).
from app.domains.dashboard.adapter.outbound.external.sec_edgar_announcement_client import (
    SecEdgarAnnouncementClient,
)
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


async def _collect_announcements(ticker: str, start_date, end_date) -> List[Dict[str, Any]]:
    """공시 수집 — region 분기 (OKR 1 P1.5).

    - 한국 종목 (.KS/.KQ/6자리 숫자): DART list.json (corp_code 매핑 후)
    - 미국 종목 (영문): SEC EDGAR 8-K
    """
    region = MarketRegionResolver.resolve(ticker)
    if region.is_korea():
        return await _collect_dart_announcements(ticker, start_date, end_date)
    return await _collect_sec_announcements(ticker, start_date, end_date)


async def _collect_sec_announcements(ticker: str, start_date, end_date) -> List[Dict[str, Any]]:
    """SEC EDGAR 8-K — 미국 종목."""
    try:
        events = await SecEdgarAnnouncementClient().fetch_announcements(
            ticker=ticker, start_date=start_date, end_date=end_date,
        )
    except Exception as exc:
        logger.warning("[CausalityAgent] SEC EDGAR 공시 예외: %s", exc)
        return []

    items: List[Dict[str, Any]] = []
    for ev in events:
        items.append({
            "date": ev.date.isoformat(),
            "type": ev.type.value if hasattr(ev.type, "value") else str(ev.type),
            "title": ev.title or "",
            "source": ev.source or "sec_edgar",
            "url": ev.url or "",
            "items_str": getattr(ev, "items_str", "") or "",
        })
    return items


async def _collect_dart_announcements(ticker: str, start_date, end_date) -> List[Dict[str, Any]]:
    """DART list.json — 한국 종목. corp_code 매핑 실패 시 빈 배열 (graceful)."""
    from app.domains.causality_agent.adapter.outbound.external.dart_announcement_client import (
        DartAnnouncementClient,
    )
    from app.infrastructure.cache.redis_client import redis_client
    from app.infrastructure.external.corp_code_mapper import ticker_to_corp_code

    corp_code = await ticker_to_corp_code(ticker, redis_client=redis_client)
    if not corp_code:
        logger.warning(
            "[CausalityAgent] DART corp_code 매핑 실패 — ticker=%s (영문/미정의 종목 또는 DART 누락)",
            ticker,
        )
        return []

    try:
        return await DartAnnouncementClient().fetch_announcements(
            ticker=ticker, corp_code=corp_code,
            start_date=start_date, end_date=end_date,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CausalityAgent] DART 공시 예외: %s", exc)
        return []


async def _collect_analyst_recommendations(ticker: str) -> List[Dict[str, Any]]:
    """Finnhub buy/hold/sell 월별 트렌드. 미국 종목만 의미. API 키 없거나 비-US 면 빈 배열."""
    region = MarketRegionResolver.resolve(ticker)
    if region.is_korea() or _is_index_ticker(ticker):
        return []
    try:
        raw = await FinnhubNewsClient().get_recommendation_trend(ticker)
    except Exception as exc:
        logger.warning("[CausalityAgent] Finnhub recommendation 예외: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        out.append({
            "period": rec.get("period", ""),
            "buy": int(rec.get("buy", 0) or 0),
            "hold": int(rec.get("hold", 0) or 0),
            "sell": int(rec.get("sell", 0) or 0),
            "strong_buy": int(rec.get("strongBuy", 0) or 0),
            "strong_sell": int(rec.get("strongSell", 0) or 0),
        })
    return out


async def collect_non_economic(state: CausalityAgentState) -> Dict[str, Any]:
    """VIX·원유·금·미국채·엔화 + 뉴스 + GPR + 공시(SEC/DART) + 분석가 추천을 병렬 수집한다.

    공시는 ticker region 따라 분기 — 미국 종목은 SEC EDGAR 8-K, 한국 종목은
    DART list.json. 한국 종목 corp_code 매핑 실패 시 빈 배열 graceful (OKR 1 P1.5).
    """
    ticker = state["ticker"]
    start_date = state["start_date"]
    end_date = state["end_date"]
    errors: list = list(state.get("errors", []))

    logger.info(
        "[CausalityAgent] [2/3] 연관자산 + 뉴스 + GPR + 공시 + 분석가 추천 + 시장/섹터 벤치마크 수집 시작"
    )
    related_task = RelatedAssetsClient().fetch(start_date, end_date)
    news_task = _collect_news(ticker, start_date, end_date)
    gpr_task = GprIndexClient().fetch(start_date, end_date)
    announcements_task = _collect_announcements(ticker, start_date, end_date)
    rec_task = _collect_analyst_recommendations(ticker)
    benchmark_task = MarketBenchmarkClient().fetch(ticker, start_date, end_date)
    sector_task = SectorBenchmarkClient().fetch(ticker, start_date, end_date)

    (
        related_result,
        news_result,
        gpr_result,
        ann_result,
        rec_result,
        benchmark_result,
        sector_result,
    ) = await asyncio.gather(
        related_task,
        news_task,
        gpr_task,
        announcements_task,
        rec_task,
        benchmark_task,
        sector_task,
        return_exceptions=True,
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

    announcements: list = []
    if isinstance(ann_result, Exception):
        msg = f"공시 수집 실패: {ann_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        announcements = ann_result

    analyst_recommendations: list = []
    if isinstance(rec_result, Exception):
        msg = f"분석가 추천 수집 실패: {rec_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        analyst_recommendations = rec_result

    market_benchmark = None
    if isinstance(benchmark_result, Exception):
        msg = f"시장 벤치마크 수집 실패: {benchmark_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        market_benchmark = benchmark_result

    sector_benchmark = None
    if isinstance(sector_result, Exception):
        msg = f"섹터 벤치마크 수집 실패: {sector_result}"
        logger.warning("[CausalityAgent] %s", msg)
        errors.append(msg)
    else:
        sector_benchmark = sector_result

    mb_label = (
        f"{market_benchmark['symbol']}({len(market_benchmark.get('bars', []))})"
        if market_benchmark else "none"
    )
    sb_label = (
        f"{sector_benchmark['symbol']}({len(sector_benchmark.get('bars', []))})"
        if sector_benchmark else "none"
    )
    logger.info(
        "[CausalityAgent] [2/3] 완료: assets=%d, news=%d, gpr=%d, ann=%d, rec=%d, mb=%s, sb=%s",
        len(related_assets),
        len(news_articles),
        len(gpr_observations),
        len(announcements),
        len(analyst_recommendations),
        mb_label,
        sb_label,
    )
    return {
        "related_assets": related_assets,
        "news_articles": news_articles,
        "gpr_observations": gpr_observations,
        "announcements": announcements,
        "analyst_recommendations": analyst_recommendations,
        "market_benchmark": market_benchmark,
        "sector_benchmark": sector_benchmark,
        "errors": errors,
    }
