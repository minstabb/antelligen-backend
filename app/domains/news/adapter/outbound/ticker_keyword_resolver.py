from app.domains.news.application.port.ticker_keyword_resolver_port import TickerKeywordResolverPort
from app.domains.stock.application.port.stock_repository import StockRepository

# 자동 조회 외에 추가 synonym이 필요한 종목 (stock_name과 다른 별칭)
_SYNONYM_OVERRIDES: dict[str, list[str]] = {
    "005380": ["현대차", "현대자동차"],
    "000270": ["기아", "기아차"],
    "051910": ["LG화학"],
    "035420": ["네이버", "NAVER"],
    "035720": ["카카오"],
}


class TickerKeywordResolver(TickerKeywordResolverPort):

    def __init__(self, stock_repository: StockRepository) -> None:
        self._repo = stock_repository

    async def resolve(self, ticker: str) -> list[str]:
        # synonym override가 있으면 우선 사용
        if ticker in _SYNONYM_OVERRIDES:
            return _SYNONYM_OVERRIDES[ticker]

        # stock_name을 DB(CSV)에서 동적 조회
        stock = await self._repo.find_by_ticker(ticker)
        if stock:
            return [stock.stock_name]

        return []
