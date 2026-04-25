from enum import Enum
from typing import List


class InvestmentInfoType(str, Enum):
    """금리·유가·환율 및 주요 매크로/자산 지표 유형."""

    # 기존 3종 (하위 호환)
    INTEREST_RATE = "interest_rate"        # 미국 10년물 국채 금리 (= US_T10Y 와 동일)
    OIL_PRICE = "oil_price"                # WTI 원유
    EXCHANGE_RATE = "exchange_rate"        # USD/KRW

    # 추가 지표
    VIX = "vix"                            # CBOE 변동성 지수
    DXY = "dxy"                            # 달러인덱스 (브로드)
    KOSPI_200 = "kospi_200"                # 코스피 200 지수
    NASDAQ_100 = "nasdaq_100"              # 나스닥 100 지수
    SP_500 = "sp_500"                      # S&P 500 지수
    GOLD = "gold"                          # 금 (런던 오전 고시)
    USD_JPY = "usd_jpy"                    # 달러/엔
    US_T2Y = "us_t2y"                      # 미국 2년물 국채 금리
    US_T10Y = "us_t10y"                    # 미국 10년물 국채 금리
    US_T20Y = "us_t20y"                    # 미국 20년물 국채 금리
    DRAM_EXCHANGE = "dram_exchange"        # DRAM 가격 지표 (반도체 PPI 대리)
    BALTIC_DRY_INDEX = "baltic_dry_index"  # 발틱 운임지수 (BDRY ETF 대리)

    @property
    def display_name(self) -> str:
        return _DISPLAY_NAMES[self]

    @classmethod
    def parse(cls, raw: str) -> "InvestmentInfoType":
        if raw is None:
            raise ValueError("투자 정보 유형이 비어있습니다.")
        key = raw.strip()
        # 영문 정규화
        norm = key.lower().replace("-", "_").replace(" ", "_").replace("/", "_")
        if norm in _ALIASES:
            return _ALIASES[norm]
        # 한글 원본 매칭
        if key in _ALIASES_KR:
            return _ALIASES_KR[key]
        # 한글 공백 제거 매칭
        compact = key.replace(" ", "")
        if compact in _ALIASES_KR:
            return _ALIASES_KR[compact]
        raise ValueError(f"지원하지 않는 투자 정보 유형입니다: '{raw}'")

    @classmethod
    def supported(cls) -> List[str]:
        return [m.value for m in cls]


_DISPLAY_NAMES = {
    InvestmentInfoType.INTEREST_RATE: "금리 (미 10년물)",
    InvestmentInfoType.OIL_PRICE: "유가 (WTI)",
    InvestmentInfoType.EXCHANGE_RATE: "환율 (USD/KRW)",
    InvestmentInfoType.VIX: "VIX",
    InvestmentInfoType.DXY: "달러인덱스",
    InvestmentInfoType.KOSPI_200: "코스피 200",
    InvestmentInfoType.NASDAQ_100: "나스닥 100",
    InvestmentInfoType.SP_500: "S&P 500",
    InvestmentInfoType.GOLD: "금",
    InvestmentInfoType.USD_JPY: "USD/JPY",
    InvestmentInfoType.US_T2Y: "미국 2년물",
    InvestmentInfoType.US_T10Y: "미국 10년물",
    InvestmentInfoType.US_T20Y: "미국 20년물",
    InvestmentInfoType.DRAM_EXCHANGE: "디램익스체인지 (반도체 PPI 대리)",
    InvestmentInfoType.BALTIC_DRY_INDEX: "발틱운임지수 (BDRY ETF 대리)",
}

# 영문/숫자 alias (소문자, 공백/하이픈/슬래시 → 언더스코어)
_ALIASES: dict[str, InvestmentInfoType] = {
    # interest rate (legacy)
    "interest_rate": InvestmentInfoType.INTEREST_RATE,
    "interest": InvestmentInfoType.INTEREST_RATE,
    "rate": InvestmentInfoType.INTEREST_RATE,
    # oil
    "oil_price": InvestmentInfoType.OIL_PRICE,
    "oil": InvestmentInfoType.OIL_PRICE,
    "crude": InvestmentInfoType.OIL_PRICE,
    "wti": InvestmentInfoType.OIL_PRICE,
    # fx usd/krw
    "exchange_rate": InvestmentInfoType.EXCHANGE_RATE,
    "exchange": InvestmentInfoType.EXCHANGE_RATE,
    "fx": InvestmentInfoType.EXCHANGE_RATE,
    "usdkrw": InvestmentInfoType.EXCHANGE_RATE,
    "usd_krw": InvestmentInfoType.EXCHANGE_RATE,
    # vix
    "vix": InvestmentInfoType.VIX,
    "vixcls": InvestmentInfoType.VIX,
    # dxy
    "dxy": InvestmentInfoType.DXY,
    "dollar_index": InvestmentInfoType.DXY,
    "dollarindex": InvestmentInfoType.DXY,
    "usd_index": InvestmentInfoType.DXY,
    # kospi 200
    "kospi_200": InvestmentInfoType.KOSPI_200,
    "kospi200": InvestmentInfoType.KOSPI_200,
    "ks200": InvestmentInfoType.KOSPI_200,
    # nasdaq 100
    "nasdaq_100": InvestmentInfoType.NASDAQ_100,
    "nasdaq100": InvestmentInfoType.NASDAQ_100,
    "ndx": InvestmentInfoType.NASDAQ_100,
    # s&p 500
    "sp_500": InvestmentInfoType.SP_500,
    "sp500": InvestmentInfoType.SP_500,
    "spx": InvestmentInfoType.SP_500,
    "s&p500": InvestmentInfoType.SP_500,
    "s&p_500": InvestmentInfoType.SP_500,
    # gold
    "gold": InvestmentInfoType.GOLD,
    "xau": InvestmentInfoType.GOLD,
    "xauusd": InvestmentInfoType.GOLD,
    # usd/jpy
    "usd_jpy": InvestmentInfoType.USD_JPY,
    "usdjpy": InvestmentInfoType.USD_JPY,
    "jpy": InvestmentInfoType.USD_JPY,
    # US treasuries
    "us_t2y": InvestmentInfoType.US_T2Y,
    "us2y": InvestmentInfoType.US_T2Y,
    "dgs2": InvestmentInfoType.US_T2Y,
    "us_t10y": InvestmentInfoType.US_T10Y,
    "us10y": InvestmentInfoType.US_T10Y,
    "dgs10": InvestmentInfoType.US_T10Y,
    "us_t20y": InvestmentInfoType.US_T20Y,
    "us20y": InvestmentInfoType.US_T20Y,
    "dgs20": InvestmentInfoType.US_T20Y,
    # DRAM
    "dram_exchange": InvestmentInfoType.DRAM_EXCHANGE,
    "dramexchange": InvestmentInfoType.DRAM_EXCHANGE,
    "dram": InvestmentInfoType.DRAM_EXCHANGE,
    "semiconductor_ppi": InvestmentInfoType.DRAM_EXCHANGE,
    # Baltic Dry Index
    "baltic_dry_index": InvestmentInfoType.BALTIC_DRY_INDEX,
    "bdi": InvestmentInfoType.BALTIC_DRY_INDEX,
    "bdry": InvestmentInfoType.BALTIC_DRY_INDEX,
    "baltic": InvestmentInfoType.BALTIC_DRY_INDEX,
}

# 한글 alias (그대로 + 공백 제거 버전 모두)
_ALIASES_KR: dict[str, InvestmentInfoType] = {
    "금리": InvestmentInfoType.INTEREST_RATE,
    "유가": InvestmentInfoType.OIL_PRICE,
    "환율": InvestmentInfoType.EXCHANGE_RATE,
    "VIX": InvestmentInfoType.VIX,
    "vix지수": InvestmentInfoType.VIX,
    "VIX지수": InvestmentInfoType.VIX,
    "달러인덱스": InvestmentInfoType.DXY,
    "달러 인덱스": InvestmentInfoType.DXY,
    "코스피200": InvestmentInfoType.KOSPI_200,
    "코스피 200": InvestmentInfoType.KOSPI_200,
    "나스닥100": InvestmentInfoType.NASDAQ_100,
    "나스닥 100": InvestmentInfoType.NASDAQ_100,
    "S&P500": InvestmentInfoType.SP_500,
    "S&P 500": InvestmentInfoType.SP_500,
    "금": InvestmentInfoType.GOLD,
    "달러엔": InvestmentInfoType.USD_JPY,
    "달러/엔": InvestmentInfoType.USD_JPY,
    "엔달러": InvestmentInfoType.USD_JPY,
    "미국2년물": InvestmentInfoType.US_T2Y,
    "미국 2년물": InvestmentInfoType.US_T2Y,
    "2년물": InvestmentInfoType.US_T2Y,
    "미국10년물": InvestmentInfoType.US_T10Y,
    "미국 10년물": InvestmentInfoType.US_T10Y,
    "10년물": InvestmentInfoType.US_T10Y,
    "미국20년물": InvestmentInfoType.US_T20Y,
    "미국 20년물": InvestmentInfoType.US_T20Y,
    "20년물": InvestmentInfoType.US_T20Y,
    "디램익스체인지": InvestmentInfoType.DRAM_EXCHANGE,
    "디램 익스체인지": InvestmentInfoType.DRAM_EXCHANGE,
    "디램": InvestmentInfoType.DRAM_EXCHANGE,
    "DRAM": InvestmentInfoType.DRAM_EXCHANGE,
    "DRAMeXchange": InvestmentInfoType.DRAM_EXCHANGE,
    "발틱운임지수": InvestmentInfoType.BALTIC_DRY_INDEX,
    "발틱 운임지수": InvestmentInfoType.BALTIC_DRY_INDEX,
    "발틱운임": InvestmentInfoType.BALTIC_DRY_INDEX,
    "BDI": InvestmentInfoType.BALTIC_DRY_INDEX,
}
