from app.domains.news.application.port.ticker_keyword_resolver_port import TickerKeywordResolverPort
from app.domains.stock.application.port.stock_repository import StockRepository

# 자동 조회 외에 추가 synonym이 필요한 종목 (stock_name과 다른 별칭)
_SYNONYM_OVERRIDES: dict[str, list[str]] = {
    # ─── 국장 동의어 (DB stock_name 단일 → 검색 폭 좁은 경우) ───
    "005380": ["현대차", "현대자동차"],
    "000270": ["기아", "기아차"],
    "051910": ["LG화학"],
    "035420": ["네이버", "NAVER"],
    "035720": ["카카오"],
    "005490": ["포스코", "POSCO홀딩스"],
    "352820": ["하이브", "HYBE"],
    "041510": ["에스엠", "SM엔터", "SM엔터테인먼트"],
    "035900": ["JYP엔터", "JYP Entertainment"],
    "122870": ["와이지엔터", "YG엔터테인먼트"],
    "036570": ["엔씨소프트", "NCsoft"],
    "247540": ["에코프로비엠", "에코프로 비엠"],
    "086520": ["에코프로"],
    "373220": ["LG에너지솔루션", "LG엔솔"],
    "006400": ["삼성SDI"],
    "251270": ["넷마블"],
    "259960": ["크래프톤"],
    "293490": ["카카오게임즈"],
    # ─── 미장 (US) - DB 미등록, override 필수 ───
    "AAPL": ["Apple", "애플"],
    "MSFT": ["Microsoft", "마이크로소프트"],
    "GOOGL": ["Google", "구글", "알파벳"],
    "AMZN": ["Amazon", "아마존"],
    "META": ["Meta", "메타", "페이스북"],
    "TSLA": ["Tesla", "테슬라"],
    "NVDA": ["NVIDIA", "엔비디아"],
    "AMD": ["AMD"],
    "PLTR": ["Palantir", "팔란티어"],
    "NFLX": ["Netflix", "넷플릭스"],
    "AVGO": ["Broadcom", "브로드컴"],
    "TSM": ["TSMC"],
    "COIN": ["Coinbase", "코인베이스"],
    "MSTR": ["MicroStrategy", "마이크로스트래티지"],
    "GME": ["GameStop", "게임스톱"],
    "SMCI": ["Super Micro", "슈퍼마이크로"],
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
