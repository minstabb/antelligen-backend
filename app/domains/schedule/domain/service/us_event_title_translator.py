"""미국(US) 경제 일정 영문 타이틀 → 한글 표시명 변환 도메인 서비스.

FRED `/releases` 가 반환하는 release name 은 영어이며 그대로 화면에 노출하면
'다가오는 경제 일정' 섹션이 영문 일색이 된다. 이 모듈은 대표 US release 명을
한글 표시명으로 매핑한다.

- 매핑 규칙: 더 구체적인 패턴이 먼저 매칭되도록 길이가 긴 키를 앞에 배치한다.
  (예: "Producer Price Index by Industry" → "Producer Price Index" 보다 먼저)
- 매칭은 대소문자 무시(substring) 방식. release 명에 부가 수식어가 붙는 경우에도
  핵심 키워드만 들어 있으면 한글로 치환된다.
- 매핑되지 않은 release 는 원문(영문)을 그대로 반환한다.
"""

from __future__ import annotations

from typing import List, Tuple

# (영문 패턴, 한글 표시명) — 매칭 우선순위는 리스트 순서대로
# FRED press_release=True release 중 시장에서 자주 인용되는 항목 위주
_US_TITLE_MAPPINGS: List[Tuple[str, str]] = [
    # 물가 지표
    ("Producer Price Index by Industry", "생산자물가지수 (산업별)"),
    ("Producer Price Index by Commodity", "생산자물가지수 (품목별)"),
    ("Producer Price Index", "생산자물가지수 (PPI)"),
    ("Consumer Price Index", "소비자물가지수 (CPI)"),
    ("Personal Consumption Expenditures Price Index", "개인소비지출 물가지수 (PCE)"),
    ("Personal Income and Outlays", "개인소득·지출 (PCE 포함)"),
    ("Real Earnings", "실질소득"),
    ("Import and Export Price Indexes", "수출입 물가지수"),

    # 고용 / 노동
    ("Employment Situation", "고용 상황 (비농업 고용)"),
    ("Job Openings and Labor Turnover", "구인·이직 보고서 (JOLTS)"),
    ("Unemployment Insurance Weekly Claims", "주간 신규 실업수당 청구"),
    ("Productivity and Costs", "생산성·단위노동비용"),
    ("Employment Cost Index", "고용비용지수 (ECI)"),
    ("ADP National Employment", "ADP 민간고용 보고서"),

    # 성장 / 활동
    ("Gross Domestic Product", "국내총생산 (GDP)"),
    ("GDP by Industry", "산업별 GDP"),
    ("Industrial Production and Capacity Utilization", "산업생산·설비가동률"),
    ("Industrial Production", "산업생산"),
    ("Capacity Utilization", "설비가동률"),
    ("Beige Book", "베이지북"),
    ("Leading Economic Indicators", "경기선행지수"),
    ("Conference Board Consumer Confidence", "컨퍼런스보드 소비자신뢰지수"),
    ("Consumer Confidence", "소비자신뢰지수"),
    ("University of Michigan Consumer Sentiment", "미시간대 소비자심리지수"),
    ("Empire State Manufacturing Survey", "엠파이어 스테이트 제조업지수"),
    ("Philadelphia Fed Manufacturing", "필라델피아 연준 제조업지수"),
    ("Chicago Fed National Activity Index", "시카고 연준 전미경제활동지수"),

    # 소매 / 도매 / 재고
    ("Advance Monthly Sales for Retail Trade", "월간 소매판매 속보치"),
    ("Advance Retail Sales", "소매판매 속보치"),
    ("Retail Trade", "소매판매"),
    ("Wholesale Trade", "도매판매"),
    ("Wholesale Inventories", "도매재고"),
    ("Manufacturing and Trade Inventories and Sales", "제조·유통 재고·판매"),
    ("Business Inventories", "기업재고"),

    # 주문 / 출하
    ("Advance Report on Durable Goods", "내구재 주문 속보치"),
    ("Durable Goods", "내구재 주문"),
    ("Manufacturers' Shipments, Inventories, and Orders", "공장 주문 (제조업 출하·재고·신규수주)"),
    ("Factory Orders", "공장 주문"),

    # 주택
    ("New Residential Construction", "신규 주택착공·건축허가"),
    ("Housing Starts", "주택착공 건수"),
    ("Building Permits", "주택건설 허가"),
    ("New Residential Sales", "신규 주택판매"),
    ("Existing Home Sales", "기존주택 판매"),
    ("Pending Home Sales", "잠정주택판매"),
    ("S&P CoreLogic Case-Shiller", "S&P 케이스-실러 주택가격지수"),
    ("Construction Spending", "건설지출"),

    # 무역 / 국제수지
    ("U.S. International Trade in Goods and Services", "미국 상품·서비스 무역수지"),
    ("International Trade in Goods and Services", "상품·서비스 무역수지"),
    ("Advance U.S. International Trade in Goods", "상품 무역수지 속보치"),
    ("Trade Balance", "무역수지"),
    ("U.S. International Transactions", "미국 국제수지"),

    # 통화 / 금융
    ("FOMC", "FOMC 회의"),
    ("Federal Open Market Committee", "FOMC 회의"),
    ("H.6 Money Stock Measures", "통화량 (M1/M2)"),
    ("Money Stock Measures", "통화량 (M1/M2)"),
    ("Senior Loan Officer Opinion Survey", "선임 대출담당자 서베이 (SLOOS)"),
    ("Consumer Credit", "소비자 신용"),

    # 정부 / 재정
    ("Monthly Treasury Statement", "월간 재무부 재정수지"),
    ("Treasury International Capital", "재무부 국제자본흐름 (TIC)"),

    # 기타 정기 보고서
    ("Advance Quarterly Services", "분기 서비스업 매출 속보치"),
    ("Quarterly Services", "분기 서비스업 매출"),
    ("Quarterly Financial Report", "분기 기업재무보고서"),
    ("State Personal Income", "주별 개인소득"),
    ("County and Metro Area Personal Income", "카운티·대도시 개인소득"),
]


def translate_us_event_title(title: str) -> str:
    """미국 경제 일정 영문 release 명을 한글 표시명으로 변환.

    매핑된 패턴이 없으면 원문 그대로 반환한다. 호출 측에서는 country == 'US' 인
    이벤트에 대해서만 호출하는 것을 권장한다.
    """
    if not title:
        return title
    lowered = title.lower()
    for pattern, korean in _US_TITLE_MAPPINGS:
        if pattern.lower() in lowered:
            return korean
    return title
