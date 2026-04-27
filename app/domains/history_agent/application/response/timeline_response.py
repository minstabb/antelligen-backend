from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class HypothesisSource(BaseModel):
    label: str                              # "Reuters", "DART", "Bloomberg"
    url: Optional[str] = None               # 1차 URL (없으면 라벨만 표시)


class HypothesisResult(BaseModel):
    hypothesis: str
    supporting_tools_called: List[str]
    # KR2-(3) 신뢰도 등급 — HIGH | MEDIUM | LOW. 누락/이상치는 LOW 로 다운그레이드.
    confidence: str = "LOW"
    # KR2-(2) 추정 원인 계층 — DIRECT(종목 고유) | SUPPORTING(보조 컨텍스트) | MARKET(시장/매크로).
    layer: str = "SUPPORTING"
    # KR2-(3) 출처 URL+라벨. 1차 출처 우선, 부재 시 빈 배열.
    sources: List[HypothesisSource] = []
    # KR2-(3) 정량 근거(지표명·수치·날짜). 없으면 None.
    evidence: Optional[str] = None


class TimelineEvent(BaseModel):
    title: str                           # AI 생성 이벤트 타이틀
    date: date
    category: str   # PRICE | CORPORATE | ANNOUNCEMENT | MACRO | NEWS
    type: str
    detail: str
    source: Optional[str] = None
    url: Optional[str] = None
    change_pct: Optional[float] = None   # PRICE 이벤트 변화율(%) — pre-filter 중요도 산정용
    causality: Optional[List[HypothesisResult]] = None
    # ETF holdings 분해 시 각 constituent 이벤트에 설정. ETF 자체 이벤트는 None.
    constituent_ticker: Optional[str] = None
    weight_pct: Optional[float] = None
    # 뉴스 이벤트용 감성 점수(-1..1). 소스에 따라 없을 수 있음.
    sentiment: Optional[float] = None
    # 매크로 이벤트 역사적 중요도(0..1). MACRO·MACRO_CONTEXT 이외엔 None.
    importance_score: Optional[float] = None
    # 공시 분류 v2 — 1~5 정수 척도. CORPORATE/ANNOUNCEMENT만 채워짐 (PR1).
    importance_score_1to5: Optional[int] = None
    # 어느 분류기 버전이 type/score를 결정했는지("v1"=규칙 베이스, "v2"=LLM 재분류).
    classifier_version: Optional[str] = None
    # SEC 8-K raw Item 코드(예: "1.01,9.01"). KR A.1 빈도 분석 / classifier 입력에 사용.
    items_str: Optional[str] = None
    # PR2/PR3 — Abnormal return 메트릭. EQUITY 한정, 매일 KST 08:00 batch로 채워진다.
    # 미계산/비-EQUITY/데이터 부족 시 None.
    abnormal_return_5d: Optional[float] = None
    abnormal_return_20d: Optional[float] = None
    ar_status: Optional[str] = None
    benchmark_ticker: Optional[str] = None
    # KR1 — MACRO 이벤트의 인과 분류. "TYPE_A"(원인 — FOMC/CPI 등 발표) /
    # "TYPE_B"(결과 — VIX/금리/환율 등 시장 반응). 비-MACRO 이벤트와 미정의 type 은 None.
    macro_type: Optional[str] = None
    # KR2 — Type B 이벤트의 추정 사유. cross-ref 매칭 또는 LLM 추정 결과. 미해결 시 None.
    reason: Optional[str] = None
    # KR2-(3)/KR3 — 사유 신뢰도. "HIGH"(같은 날 Type A cross-ref) / "LOW"(LLM 추정).
    reason_confidence: Optional[str] = None
    # KR2-(3)/KR3 — 사유 근거(특정 사건명/발표명). LLM 추정 시 출처 강제 제출 + 미제시 시 reason None.
    reason_evidence: Optional[str] = None


class TimelineResponse(BaseModel):
    # 매크로 전용 타임라인은 ticker 없이 region 기반으로도 반환된다.
    ticker: Optional[str] = None
    # ADR-0001: /timeline 은 chart_interval(봉 단위), /macro-timeline 은 lookback_range(조회 기간).
    # 시맨틱이 다르므로 단일 period 필드로 합치지 않고 각자 자기 엔드포인트에서만 채운다.
    chart_interval: Optional[str] = None
    lookback_range: Optional[str] = None
    count: int
    events: List[TimelineEvent]
    is_etf: bool = False
    # Literal 제한을 완화 — UNKNOWN이나 앞으로 추가될 원본 quote_type이 그대로 전달될 수 있도록.
    asset_type: str = "EQUITY"
    region: Optional[str] = None
