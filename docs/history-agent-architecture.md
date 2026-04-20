# history_agent — LLM-readable spec

목적: Claude가 이 문서 1개만 읽고 history_agent 관련 질문에 답하거나 수정할 수 있도록, 파일·라인·심볼을 밀도 있게 기록. 산문 설명 최소화.

Root: `app/domains/history_agent/`

---

## 질문 → 위치 빠른 매핑

| 질문 | 직행 파일:라인 |
|---|---|
| 엔드포인트 정의 | `adapter/inbound/api/history_agent_router.py` |
| 메인 오케스트레이션 | `application/usecase/history_agent_usecase.py:298` (`execute`) |
| 자산유형 3분기 진입점 | `history_agent_usecase.py:322` (`get_quote_type` 호출) |
| EQUITY 데이터 수집 병렬 호출 | `history_agent_usecase.py:361` |
| INDEX 전용 경로 | `history_agent_usecase.py:443` (`_execute_index_timeline`) |
| 지수 → 리전 매핑 | `history_agent_usecase.py:78` (`_INDEX_REGION`) |
| MACRO 이벤트 변환 | `history_agent_usecase.py:190` (`_from_macro_events`) |
| causality 호출부 | `history_agent_usecase.py:235` (`_enrich_causality`) |
| causality 내부 실행 | `history_agent_usecase.py:215` (`_run_causality`) |
| 타이틀 생성 엔진 | `application/service/title_generation_service.py` |
| PRICE 중요도 함수 | `title_generation_service.py:130` (`price_importance`) |
| Fallback 타이틀 맵 | `title_generation_service.py:87` (`FALLBACK_TITLE`) |
| EQUITY PRICE 타이틀 프롬프트 | `title_generation_service.py:21` (`PRICE_TITLE_SYSTEM`) |
| INDEX PRICE 타이틀 프롬프트 | `title_generation_service.py:40` (`INDEX_PRICE_TITLE_SYSTEM`) |
| MACRO 타이틀 프롬프트 | `title_generation_service.py:59` (`MACRO_TITLE_SYSTEM`) |
| MACRO 타이틀 생성 | `title_generation_service.py:246` (`enrich_macro_titles`) |
| 영문 공시 한글 요약 | `history_agent_usecase.py:91` (`_summarize_to_korean`) |
| FRED 시리즈·리전 설정 | `dashboard/.../get_economic_events_usecase.py:25` (`_SERIES_CONFIG`, `_REGION_SERIES`) |
| DB 캐시 조회/저장 | `adapter/outbound/persistence/event_enrichment_repository_impl.py` |
| ORM 테이블 정의 | `infrastructure/orm/event_enrichment_orm.py` |
| 응답 DTO | `application/response/timeline_response.py` |
| 배치 타이틀 전용 UseCase | `application/usecase/generate_titles_usecase.py` |

---

## 디렉터리 (실제 파일만)

```
history_agent/
├── adapter/
│   ├── inbound/api/history_agent_router.py
│   └── outbound/persistence/event_enrichment_repository_impl.py
├── application/
│   ├── port/out/event_enrichment_repository_port.py
│   ├── request/title_request.py
│   ├── response/{timeline_response.py, title_response.py}
│   ├── service/title_generation_service.py
│   └── usecase/{history_agent_usecase.py, generate_titles_usecase.py}
├── domain/entity/event_enrichment.py
└── infrastructure/
    ├── orm/event_enrichment_orm.py
    └── mapper/event_enrichment_mapper.py
```

의존 방향: Adapter → Application → Domain. Domain은 순수 Python (`EventEnrichment`는 dataclass).

---

## 엔드포인트

prefix: `/history-agent`

| Method | Path | Handler | 비고 |
|---|---|---|---|
| GET | `/timeline` | `get_timeline` | 일괄 응답 |
| GET | `/timeline/stream` | `stream_timeline` | SSE: `progress`/`done`/`error` |
| POST | `/titles` | `generate_titles` | 배치 타이틀만, `GenerateTitlesUseCase` |

쿼리: `ticker`, `period ∈ {1D,1W,1M,1Y}`, `enrich_titles: bool`
`ticker`가 6자리 숫자면 `_resolve_corp_code()`로 DART `corp_code` 자동 조회 (router.py:51).

---

## HistoryAgentUseCase.execute() 플로우

```
0. Redis GET "history_agent:{ticker}:{period}[:no-titles]"  (TTL 3600s)
   HIT → 즉시 반환

0-1. AssetTypePort.get_quote_type(ticker)                  ← 자산유형 3분기 진입점 (:322)
     asset_type ∈ {EQUITY, INDEX, ETF, UNKNOWN}

     ETF    → events=[], is_etf=True, asset_type="ETF" 반환 후 캐시       (done=100)
     INDEX  → _execute_index_timeline() 위임 [아래 INDEX 경로 참고]
     EQUITY/UNKNOWN → 아래 계속
```

### EQUITY / UNKNOWN 경로 (풀 파이프라인)

```
1. asyncio.gather(                                         ← 3개 병렬 수집 (:361)
     GetPriceEventsUseCase(ticker, period),                # Yahoo OHLCV
     GetCorporateEventsUseCase(ticker, period, corp_code), # yfinance + DART
     GetAnnouncementsUseCase(ticker, period, corp_code),   # DART or SEC EDGAR
   )

2. _load_enrichments → DB에서 (ticker, date, type, detail_hash) HIT
   HIT 분은 title/causality 즉시 주입, MISS만 new_events

3. _enrich_causality(ticker, timeline)                     ← SURGE/PLUNGE만 (:235)
   대상: category=PRICE ∧ type∈{SURGE,PLUNGE} ∧ causality is None, 상위 3건
   윈도우: event.date ±(-14, +3)일
   호출: causality_agent.run_causality_agent(...)

4. asyncio.gather(                                         ← 타이틀 & 요약
     enrich_price_titles(is_index=False),  # 중요도 Top 50만 LLM (EQUITY 프롬프트)
     enrich_other_titles,                  # CORPORATE/ANNOUNCEMENT 전체 LLM
     _enrich_announcement_details,         # 영문(ASCII 알파벳>60%) → 한글 2~3문장
   )
   enrich_titles=False면: PRICE는 rule_based_price_title만, 요약은 수행

5. _save_enrichments(new_events) → PG upsert
6. Redis SET 캐시 (1h), asset_type=asset_type
```

SSE pct (EQUITY): `data_fetch=10`, `enrichment_load=35`, `causality=55`, `title_gen=75`, `saving=90`

### INDEX 경로 (_execute_index_timeline, :443)

```
0. region = _INDEX_REGION.get(ticker, "US")                ← 지수-리전 매핑 (:78)
   ^IXIC/^GSPC/^DJI → "US" | ^KS11 → "KR" | 미지원 → "US"

1. asyncio.gather(                                         ← PRICE + MACRO 병렬 수집
     GetPriceEventsUseCase(ticker, period),                # Yahoo OHLCV (ticker 전용)
     GetEconomicEventsUseCase(period, region=region),      # FRED 시리즈 (리전 3개 병렬)
   )
   CORPORATE·ANNOUNCEMENT 수집 없음 (yfinance·DART·SEC EDGAR 호출 제로)
   MACRO 실패 시 로그 후 PRICE만 반환 (graceful degradation)

2. _load_enrichments / _apply_enrichments                  ← DB 캐시 동일 적용

3. _enrich_causality(is_index=True) → 즉시 return          ← causality=null 보장
   (개별 종목 기반 분석이 지수에 부적합; 향후 매크로 causality 확장 예정)

4. asyncio.gather(
     enrich_price_titles(is_index=True),   ← INDEX_PRICE_TITLE_SYSTEM (매크로 관점)
     enrich_macro_titles,                  ← MACRO_TITLE_SYSTEM (지표 방향·의미)
   )
   enrich_titles=False면: PRICE만 rule_based_price_title, MACRO는 fallback 유지

5. _save_enrichments → Redis SET 캐시 (1h), asset_type="INDEX"
```

SSE pct (INDEX): `data_fetch=10`, `title_gen=70`

---

## TimelineEvent 스키마

`application/response/timeline_response.py`

```python
TimelineEvent:
  title: str
  date: date
  category: "PRICE" | "CORPORATE" | "ANNOUNCEMENT" | "MACRO"
  type: str
  detail: str
  source: Optional[str]
  url: Optional[str]
  change_pct: Optional[float]              # PRICE: 변화율(%) / MACRO: 이전 대비 변화폭(%p)
  causality: Optional[List[HypothesisResult]]  # INDEX·MACRO는 항상 null

HypothesisResult: { hypothesis: str, supporting_tools_called: List[str] }

TimelineResponse:
  ticker, period, count, events
  is_etf: bool = False                     # ETF일 때만 True (하위 호환용)
  asset_type: Literal["EQUITY","INDEX","ETF","UNKNOWN"] = "EQUITY"
```

---

## 이벤트 카테고리 × 타입

| Category | Types | 출처 Adapter |
|---|---|---|
| PRICE | `HIGH_52W`(응답에서 제외), `LOW_52W`, `SURGE`, `PLUNGE`, `GAP_UP`, `GAP_DOWN` | Yahoo OHLCV로 직접 계산 |
| CORPORATE | `EARNINGS`, `DIVIDEND`, `STOCK_SPLIT`, `RIGHTS_OFFERING`, `BUYBACK`, `MANAGEMENT_CHANGE`, `DISCLOSURE` | `yfinance_corporate_port` + `DartCorporateEventClient` |
| ANNOUNCEMENT | `MERGER_ACQUISITION`, `CONTRACT`, `MAJOR_EVENT` | `sec_edgar_port` 또는 `DartAnnouncementClient` |
| MACRO | `INTEREST_RATE`, `CPI`, `UNEMPLOYMENT` | `GetEconomicEventsUseCase` → FRED API |

`_EXCLUDED_PRICE_TYPES = {"HIGH_52W"}` (타임라인에서 제외)
`_PCT_VALUE_TYPES = {"SURGE","PLUNGE","GAP_UP","GAP_DOWN"}` (`e.value` → `change_pct`로 매핑)

MACRO `detail` 포맷 예: `"기준금리 5.25% (이전: 5.00%, 변화: +0.25%p)"`

---

## MACRO 이벤트 — FRED 시리즈 설정

`dashboard/.../get_economic_events_usecase.py`

### _SERIES_CONFIG (:25)

`series_id → (event_type, label, apply_yoy)`

| Series ID | type | label | apply_yoy |
|---|---|---|---|
| `FEDFUNDS` | `INTEREST_RATE` | 기준금리 | False |
| `CPIAUCSL` | `CPI` | CPI | True (원지수 → YoY%) |
| `UNRATE` | `UNEMPLOYMENT` | 실업률 | False |
| `INTDSRKRM193N` | `INTEREST_RATE` | 기준금리 (BOK) | False |
| `CPALTT01KRM657N` | `CPI` | CPI (한국) | True (원지수 → YoY%) |
| `LRHUTTTTKRIQ156S` | `UNEMPLOYMENT` | 실업률 (한국) | False |

### _REGION_SERIES (:37)

```
"US": [FEDFUNDS, CPIAUCSL, UNRATE]
"KR": [INTDSRKRM193N, CPALTT01KRM657N, LRHUTTTTKRIQ156S]
# TODO: 글로벌 공통(유가 WTISPLC 등) 필요 시 "GLOBAL" 리전 추가
```

### _INDEX_REGION (:78, history_agent_usecase.py)

```
^IXIC, ^GSPC, ^DJI  → "US"
^KS11               → "KR"
기타                 → "US" (default)
```

---

## 타이틀 생성 (`title_generation_service.py`)

| 상수 | 값 |
|---|---|
| `TITLE_MODEL` | `"gpt-5-mini"` |
| `TITLE_BATCH` | 15 |
| `TITLE_CONCURRENCY` | 10 |
| `PRICE_LLM_TOP_N` | 50 |

`price_importance(e)` 점수:
- `abs(change_pct)`
- `+100` if `causality` 있음
- `+50` if type ∈ {SURGE, PLUNGE}
- `+30` if type = LOW_52W
- `+5` if type ∈ {GAP_UP, GAP_DOWN}

→ 상위 50건만 LLM. 나머지는 `rule_based_price_title()` (예: `"급등 (+5.2%)"`).

**시스템 프롬프트**

| 상수 | 적용 대상 | 특징 |
|---|---|---|
| `PRICE_TITLE_SYSTEM` (:21) | EQUITY PRICE | 15자, 개별 기업 원인·배경 중심 |
| `INDEX_PRICE_TITLE_SYSTEM` (:40) | INDEX PRICE | 15자, 거시경제·섹터·정책 요인 중심 |
| `MACRO_TITLE_SYSTEM` (:59) | MACRO | 15자, 지표 방향·의미 중심 (동결/완화/상회 등) |
| `OTHER_TITLE_SYSTEM` | CORPORATE·ANNOUNCEMENT | 12자 |

모두 JSON 배열 응답, 이벤트 순서 일치 필수.

`is_fallback_title(event)` — `FALLBACK_TITLE` 매핑값과 일치 여부로 미생성 판별.

**FALLBACK_TITLE MACRO 항목**

```
INTEREST_RATE → "기준금리 결정"
CPI           → "CPI 발표"
UNEMPLOYMENT  → "실업률 발표"
```

---

## 캐시 이중 구조

### L1 — Redis (응답 단위)
- Key: `history_agent:{ticker}:{period}` (+ `:no-titles` if `enrich_titles=False`)
- Value: `TimelineResponse` JSON (MACRO 이벤트 포함)
- TTL: 3600s
- `history_agent_usecase.py:303`

### L2 — PostgreSQL `event_enrichments` (이벤트 단위, 영구)
Unique: `(ticker, event_date, event_type, detail_hash)`
- `detail_hash = sha256(detail)[:16]` — detail 바뀌면 새 row
- MACRO 이벤트도 동일 키 구조로 저장됨 (ticker=지수코드, type=INTEREST_RATE 등)
- Columns: `title: Text`, `causality: JSONB`, `created_at`, `updated_at`
- Upsert: `ON CONFLICT … DO UPDATE` set `title, causality, updated_at` (`event_enrichment_repository_impl.py:40`)
- Port: `EventEnrichmentRepositoryPort` with `find_by_keys`, `upsert_bulk`

---

## 외부 포트 (대부분 `dashboard` 도메인 재사용)

| Port (import 경로) | Adapter 구현 | 역할 |
|---|---|---|
| `dashboard...StockBarsPort` | `YahooFinanceStockClient` | OHLCV |
| `dashboard...YahooFinanceCorporateEventPort` | `YahooFinanceCorporateEventClient` | 배당/분할 |
| (직접 주입) `DartCorporateEventClient` | — | 한국 기업이벤트 |
| `dashboard...SecEdgarAnnouncementPort` | `SecEdgarAnnouncementClient` | 8-K |
| (직접 주입) `DartAnnouncementClient` | — | DART 공시 |
| `dashboard...AssetTypePort` | `YahooFinanceAssetTypeClient` | EQUITY/ETF/INDEX 판별 |
| `dashboard...FredMacroPort` | `FredMacroClient` | FRED 거시경제 시리즈 |
| `history_agent...EventEnrichmentRepositoryPort` | `EventEnrichmentRepositoryImpl` | enrichment 영구 캐시 |

Router에서 수동 DI (`history_agent_router.py:84`). DI 컨테이너 없음.

---

## 주요 상수 (usecase 레벨)

```
_CACHE_TTL              = 3600     # Redis 초
_CAUSALITY_TRIGGER_TYPES= {SURGE, PLUNGE}
_MAX_CAUSALITY_EVENTS   = 3
_CAUSALITY_PRE_DAYS     = 14
_CAUSALITY_POST_DAYS    = 3
_EXCLUDED_PRICE_TYPES   = {HIGH_52W}
_PCT_VALUE_TYPES        = {SURGE, PLUNGE, GAP_UP, GAP_DOWN}

_INDEX_REGION           = {^IXIC/^GSPC/^DJI→"US", ^KS11→"KR"}   # :78
_DEFAULT_INDEX_REGION   = "US"
```

영문 판별: `_is_english_text(text)` — 길이≥30 ∧ ASCII 알파벳 비율>60%.

---

## 수정 포인트 치트시트

| 하고 싶은 일 | 건드릴 파일:라인 |
|---|---|
| ETF에도 타임라인 제공 | `history_agent_usecase.py:326` ETF 분기 제거 |
| INDEX에 CORPORATE 이벤트 추가 | `_execute_index_timeline(:443)` — corporate_uc 추가 |
| INDEX causality 활성화 (매크로용) | `_enrich_causality(:235)` `is_index` 가드 교체 + 매크로 워크플로우 연결 |
| 새 지수 → 리전 추가 (예: ^N225 → JP) | `_INDEX_REGION(:78)` 항목 추가 + `_REGION_SERIES` JP 시리즈 추가 |
| 글로벌 이벤트(유가 등) 전 지수 공통 노출 | `_REGION_SERIES` "GLOBAL" 리전 추가 + `_execute_index_timeline`에서 US+GLOBAL 병합 |
| KR MACRO 시리즈 교체 | `get_economic_events_usecase.py:37` `_REGION_SERIES["KR"]` 수정 |
| INDEX PRICE 타이틀 프롬프트 변경 | `title_generation_service.py:40` `INDEX_PRICE_TITLE_SYSTEM` |
| MACRO 타이틀 프롬프트 변경 | `title_generation_service.py:59` `MACRO_TITLE_SYSTEM` |
| EQUITY PRICE 타이틀 프롬프트 변경 | `title_generation_service.py:21` `PRICE_TITLE_SYSTEM` |
| 새 PRICE 이벤트 타입 추가 | `dashboard` 도메인의 PRICE 탐지 로직 + `FALLBACK_TITLE` + `_PCT_VALUE_TYPES` |
| causality 대상 확장 | `_CAUSALITY_TRIGGER_TYPES`, `_MAX_CAUSALITY_EVENTS` |
| 타이틀 LLM 개수 조정 | `PRICE_LLM_TOP_N`, `TITLE_BATCH`, `TITLE_CONCURRENCY` |
| 캐시 TTL | `_CACHE_TTL` |
| 새 공시 소스 추가 | `GetAnnouncementsUseCase` (`dashboard` 도메인) + 라우터 DI |
| 영문→한글 요약 프롬프트 | `_ANNOUNCEMENT_SUMMARY_SYSTEM` |

---

## 관련 외부 도메인

- **`dashboard`** — 모든 데이터 수집 UseCase (`GetPriceEventsUseCase`, `GetCorporateEventsUseCase`, `GetAnnouncementsUseCase`, `GetEconomicEventsUseCase`)와 외부 API 클라이언트 전부 여기 있음.
- **`causality_agent`** — `causality_agent_workflow.run_causality_agent(ticker, start_date, end_date)` 호출 (lazy import).
- **`disclosure`** — `CompanyRepositoryImpl.find_by_stock_code(ticker)` 로 DART `corp_code` 조회.

---

## 검증 안 된 가정 (변경 전 확인 필요)

- `period` → 실제 조회 기간 변환 로직 — `dashboard`의 각 UseCase 내부
- causality workflow의 반환 shape — `causality_agent.application.causality_agent_workflow`
- `AssetTypePort.get_quote_type()` 반환값이 yfinance `"MUTUALFUND"` 등 비표준 문자열일 경우 → `UNKNOWN`으로 매핑되어 EQUITY 풀 파이프라인 실행됨 (`history_agent_usecase.py:322` 조건 참고)
- INDEX 티커 중 yfinance가 `"INDEX"` 대신 다른 quoteType을 반환하는 케이스 존재 여부 — 실 호출 로그로 확인 필요
- KR FRED 시리즈 실존 여부 — `INTDSRKRM193N`, `CPALTT01KRM657N`, `LRHUTTTTKRIQ156S` 가 실제 FRED에 존재하고 데이터가 최신인지 확인 필요. 없으면 FredApiException → graceful degradation으로 MACRO 이벤트 0건 반환됨
- `CPALTT01KRM657N` 가 index level 시리즈인지 이미 % change 시리즈인지 — `apply_yoy=True` 설정 기준으로 잡혔으나 시리즈 특성 재확인 필요
