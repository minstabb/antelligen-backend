"""DART 잠정실적 수집 대상 기업 메타데이터.

KOSPI 200 · KOSDAQ 150 · 코리아 밸류업 지수(VALUEUP) 구성 종목 중 시총 상위
및 분기 잠정실적을 선공시하는 주요 종목으로 구성된 정적 universe 정의.

KRX 정기변경(연 2회: 6월·12월) 시 수동 갱신.
"""

from dataclasses import dataclass
from typing import Tuple


INDEX_KOSPI200 = "KOSPI200"
INDEX_KOSDAQ150 = "KOSDAQ150"
INDEX_VALUEUP = "VALUEUP"


@dataclass(frozen=True)
class CorpMeta:
    ticker: str               # 6자리 종목코드
    name: str
    market: str               # KOSPI | KOSDAQ
    indices: Tuple[str, ...]  # (KOSPI200, VALUEUP) 등


COMPANIES: Tuple[CorpMeta, ...] = (
    # ─────── KOSPI 대형주 (상당수 VALUEUP) ───────
    CorpMeta("005930", "삼성전자",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("000660", "SK하이닉스",             "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("373220", "LG에너지솔루션",         "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("005380", "현대차",                "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("000270", "기아",                  "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("005490", "POSCO홀딩스",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("035420", "NAVER",                "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("035720", "카카오",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("207940", "삼성바이오로직스",        "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("066570", "LG전자",                "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("051910", "LG화학",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("006400", "삼성SDI",               "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("105560", "KB금융",                "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("055550", "신한지주",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("086790", "하나금융지주",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("316140", "우리금융지주",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("024110", "기업은행",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("138930", "BNK금융지주",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("139130", "DGB금융지주",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("175330", "JB금융지주",            "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("012330", "현대모비스",             "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("028260", "삼성물산",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("096770", "SK이노베이션",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("017670", "SK텔레콤",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("030200", "KT",                   "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("033780", "KT&G",                 "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("015760", "한국전력",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("032830", "삼성생명",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("000810", "삼성화재",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("088350", "한화생명",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("005830", "DB손해보험",            "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("001450", "현대해상",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("003550", "LG",                   "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("018260", "삼성에스디에스",          "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("009150", "삼성전기",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("010130", "고려아연",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("010950", "S-Oil",                "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("034730", "SK",                   "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("068270", "셀트리온",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("000720", "현대건설",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("000100", "유한양행",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("051900", "LG생활건강",            "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("090430", "아모레퍼시픽",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("011200", "HMM",                  "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("402340", "SK스퀘어",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("012450", "한화에어로스페이스",      "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("000150", "두산",                  "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("034020", "두산에너빌리티",         "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("267250", "HD현대",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("267260", "HD현대일렉트릭",         "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("329180", "HD현대중공업",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("009540", "HD한국조선해양",         "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("064350", "현대로템",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("251270", "넷마블",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("036570", "엔씨소프트",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("000880", "한화",                  "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("009830", "한화솔루션",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("000120", "CJ대한통운",            "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("097950", "CJ제일제당",            "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("003490", "대한항공",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("003230", "삼양식품",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("035250", "강원랜드",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("011170", "롯데케미칼",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("023530", "롯데쇼핑",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("004020", "현대제철",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("001040", "CJ",                   "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("004370", "농심",                  "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("029780", "삼성카드",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("128940", "한미약품",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("302440", "SK바이오사이언스",        "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("112610", "씨에스윈드",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("010140", "삼성중공업",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("047050", "포스코인터내셔널",        "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("004990", "롯데지주",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("042660", "한화오션",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("007070", "GS리테일",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("003410", "쌍용양회",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("005940", "NH투자증권",             "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("006800", "미래에셋증권",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("016360", "삼성증권",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("071050", "한국금융지주",           "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("078930", "GS",                   "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("078520", "에이블씨엔씨",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("105630", "한세실업",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("192820", "코스맥스",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("008770", "호텔신라",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("030000", "제일기획",              "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("004170", "신세계",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("139480", "이마트",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("161390", "한국타이어앤테크놀로지",  "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("120110", "코오롱인더",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("081660", "휠라홀딩스",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("001230", "동국홀딩스",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("011070", "LG이노텍",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("010060", "OCI홀딩스",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("047810", "한국항공우주",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("161890", "한국콜마",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("006280", "녹십자",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("005440", "현대지에프홀딩스",        "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("008560", "메리츠금융지주",         "KOSPI",  (INDEX_KOSPI200, INDEX_VALUEUP)),
    CorpMeta("357430", "미래에셋비전",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("010620", "현대미포조선",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("001120", "LX인터내셔널",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("055490", "금호건설",              "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("001800", "오리온홀딩스",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("271560", "오리온",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("006260", "LS",                   "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("010120", "LS ELECTRIC",          "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("267290", "경동도시가스",           "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("108670", "LX하우시스",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("272210", "한화시스템",             "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("103140", "풍산",                  "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("214320", "이노션",                "KOSPI",  (INDEX_KOSPI200,)),
    CorpMeta("069620", "대웅제약",              "KOSPI",  (INDEX_KOSPI200,)),
    # ─────── KOSDAQ 150 ───────
    CorpMeta("247540", "에코프로비엠",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("086520", "에코프로",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("196170", "알테오젠",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("145020", "휴젤",                  "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("263750", "펄어비스",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("112040", "위메이드",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("293490", "카카오게임즈",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("041510", "에스엠",                "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("035900", "JYP Ent.",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("122870", "와이지엔터테인먼트",      "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("352820", "하이브",                "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("039030", "이오테크닉스",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("214150", "클래시스",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("357780", "솔브레인",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("403870", "HPSP",                 "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("240810", "원익IPS",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("214450", "파마리서치",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("083650", "비에이치",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("066970", "엘앤에프",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("356860", "레인보우로보틱스",        "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("141080", "리가켐바이오",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("058470", "리노공업",               "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("068760", "셀트리온제약",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("039200", "오스코텍",              "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("196300", "이엔에프테크놀로지",      "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("095340", "ISC",                  "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("095700", "제넥신",                "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("064760", "티씨케이",              "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("042700", "한미반도체",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("067310", "하나마이크론",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("108860", "셀바스AI",              "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("064290", "인텍플러스",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("005290", "동진쎄미켐",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("131970", "두산테스나",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("090460", "비에이치홀딩스",          "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("048410", "현대바이오",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("240350", "아이팩",                "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("053800", "안랩",                  "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("253450", "스튜디오드래곤",          "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("194480", "데브시스터즈",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("045100", "한양이엔지",             "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("036830", "솔브레인홀딩스",          "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("065350", "신성델타테크",           "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("017250", "인터엠",                "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("092730", "네오팜",                "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("900140", "엘브이엠씨홀딩스",        "KOSDAQ", (INDEX_KOSDAQ150,)),
    CorpMeta("226950", "고영",                  "KOSDAQ", (INDEX_KOSDAQ150,)),
)


# 시장 대표주 = UI 우선 표시(MEDIUM importance) 대상.
# (조기/특화 발표 패턴을 가진 시총 상위 종목 위주)
EARLY_PRIORITY_TICKERS: frozenset[str] = frozenset({
    "005930",  # 삼성전자
    "066570",  # LG전자
    "000660",  # SK하이닉스
    "005380",  # 현대차
    "000270",  # 기아
    "012330",  # 현대모비스
    "005490",  # POSCO홀딩스
    "051910",  # LG화학
    "006400",  # 삼성SDI
    "207940",  # 삼성바이오로직스
    "105560",  # KB금융
    "055550",  # 신한지주
    "086790",  # 하나금융지주
    "316140",  # 우리금융지주
    "035420",  # NAVER
    "035720",  # 카카오
    "017670",  # SK텔레콤
    "030200",  # KT
    "015760",  # 한국전력
    "032830",  # 삼성생명
})
