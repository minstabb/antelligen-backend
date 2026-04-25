# history_agent — LLM-readable spec

목적: Claude가 이 문서 1개만 읽고 history_agent 관련 질문에 답하거나 수정할 수 있도록, 파일·라인·심볼을 밀도 있게 기록. 산문 설명 최소화.

Root: `app/domains/history_agent/`

> **Tier 1 + Tier 2 (2026-04-20) + 데이터 소스 확장 Tier A/B/C (2026-04-21) 반영됨.** 현재 상태: PRICE/CORPORATE/ANNOUNCEMENT/MACRO/NEWS 5 카테고리 + ETF holdings 분해 + INDEX causality Phase A/B + 뉴스 fail-over 체인(Finnhub/GDELT/Yahoo/Naver) + Finnhub 애널리스트/실적 + RelatedAssets(VIX/oil/gold/UST10Y/FX) + GPR 지정학 리스크. yfinance 호출은 전부 429 backoff 래퍼 경유, asset_type은 Redis 24h 캐시. 변경 요약은 문서 말미 [Recent Changes](#recent-changes).

---

## 질문 → 위치 빠른 매핑

| 질문 | 직행 파일:라인 (또는 심볼) |
|---|---|
| 엔드포인트 정의 | `adapter/inbound/api/history_agent_router.py` |
| DI 모듈 (Depends 팩토리) | `app/domains/history_agent/di.py` |
| 메인 오케스트레이션 | `application/usecase/history_agent_usecase.py` → `HistoryAgentUseCase.execute` |
| 자산유형 명시 dispatch | `history_agent_usecase.py::execute` (EQUITY/INDEX/ETF/미지원 분기) |
| 캐시 키 빌더 | `history_agent_usecase.py::HistoryAgentUseCase._build_cache_key` (`history_agent:v3:{asset_type}:...`) |
| 뉴스 포트 | `application/port/out/news_event_port.py::NewsEventPort`, `NewsItem` |
| 뉴스 fail-over chain | `adapter/outbound/composite_news_provider.py::CompositeNewsProvider` (region=US/KR/GLOBAL) |
| 뉴스 수집 훅 | `history_agent_usecase.py::HistoryAgentUseCase._collect_news_events` |
| fundamentals 포트 | `application/port/out/fundamentals_event_port.py::FundamentalsEventPort` |
| Finnhub 레이팅·실적 어댑터 | `adapter/outbound/finnhub_fundamentals_adapter.py::FinnhubFundamentalsAdapter` |
| RelatedAssets 포트 | `application/port/out/related_assets_port.py::RelatedAssetsPort`, `GprIndexPort` |
| RelatedAssets/GPR 어댑터 | `adapter/outbound/macro_context_adapter.py` (`RelatedAssetsAdapter`, `GprIndexAdapter`) |
| yfinance 429 backoff | `dashboard/adapter/outbound/external/_yfinance_retry.py::yfinance_call_with_retry` |
| asset_type 캐싱 (24h) | `dashboard/adapter/outbound/external/cached_asset_type_adapter.py::CachedAssetTypeAdapter` |
| ETF holdings 세마포어 | `history_agent_usecase.py::_collect_holdings_events` (`history_holdings_concurrency`) |
| EQUITY 병렬 파이프라인 | `history_agent_usecase.py::execute` `asyncio.gather(_causality_then_price_titles, enrich_other_titles, _enrich_announcement_details)` |
| INDEX 전용 경로 | `history_agent_usecase.py::_execute_index_timeline` |
| ETF 전용 경로 | `history_agent_usecase.py::_execute_etf_timeline` (PRICE+MACRO+holdings) |
| ETF holdings 수집 | `history_agent_usecase.py::HistoryAgentUseCase._collect_holdings_events` |
| 지수 → 리전 매핑 | `history_agent_usecase.py::_INDEX_REGION` |
| ETF → 리전 매핑 | `history_agent_usecase.py::_ETF_REGION` |
| MACRO 이벤트 변환 | `history_agent_usecase.py::_from_macro_events` |
| causality 분기(EQUITY/INDEX) | `history_agent_usecase.py::_enrich_causality` |
| INDEX causality Phase A (규칙) | `history_agent_usecase.py::_infer_rule_based_index_causality` |
| INDEX causality Phase B (LLM) | `app/domains/causality_agent/macro/run_macro_causality_agent.py` |
| EQUITY causality 내부 실행 | `history_agent_usecase.py::_run_causality` |
| 공시 중복 후보 로깅 | `history_agent_usecase.py::_log_announcement_duplicates`, `_jaccard_similarity` |
| 타이틀 생성 엔진 | `application/service/title_generation_service.py` |
| LLM 에러 분류 | `title_generation_service.py::_classify_error`, `_is_rate_limit_error` |
| 배치 타이틀 재시도 | `title_generation_service.py::batch_titles` (JSON → 1회 재시도, rate_limit → backoff) |
| PRICE 중요도 함수 | `title_generation_service.py::price_importance` |
| Fallback 타이틀 맵 | `title_generation_service.py::FALLBACK_TITLE` (+ `macro_fallback_titles()` 병합) |
| 한글/영문 판별 | `application/service/text_utils.py::needs_korean_summary`, `contains_hangul` |
| EQUITY PRICE 타이틀 프롬프트 | `title_generation_service.py::PRICE_TITLE_SYSTEM` |
| INDEX PRICE 타이틀 프롬프트 | `title_generation_service.py::INDEX_PRICE_TITLE_SYSTEM` |
| MACRO 타이틀 프롬프트 | `title_generation_service.py::MACRO_TITLE_SYSTEM` |
| MACRO 타이틀 생성 | `title_generation_service.py::enrich_macro_titles` |
| 영문 공시 한글 요약 | `history_agent_usecase.py::_summarize_to_korean`, `_enrich_announcement_details` |
| FRED 시리즈·리전 설정 | `dashboard/.../get_economic_events_usecase.py::_SERIES_CONFIG` (4-tuple), `_REGION_SERIES`, `macro_fallback_titles()` |
| FRED 헬스 체크 | `history_agent_router.py::fred_series_health` (`GET /history-agent/admin/fred/health`) |
| ETF holdings 포트 | `dashboard/application/port/out/etf_holdings_port.py::EtfHoldingsPort` |
| ETF holdings 어댑터 | `dashboard/adapter/outbound/external/yahoo_finance_etf_holdings_client.py` |
| DB 캐시 조회/저장 | `adapter/outbound/persistence/event_enrichment_repository_impl.py` |
| detail_hash (constituent 포함) | `domain/entity/event_enrichment.py::compute_detail_hash(detail, constituent_ticker=None)` |
| ORM 테이블 정의 | `infrastructure/orm/event_enrichment_orm.py` |
| 응답 DTO | `application/response/timeline_response.py` (`constituent_ticker`, `weight_pct` 추가) |
| 배치 타이틀 전용 UseCase | `application/usecase/generate_titles_usecase.py` |
| 튜닝 파라미터 (env) | `app/infrastructure/config/settings.py` (`history_*`, `index_causality_llm_enabled`) |
| INDEX causality Phase B 골든셋 | `tests/domains/causality_agent/macro/fixtures/` |

---

## 디렉터리 (실제 파일만)

```
history_agent/
├── adapter/
│   ├── inbound/api/history_agent_router.py   (+ /admin/fred/health)
│   └── outbound/persistence/event_enrichment_repository_impl.py
├── application/
│   ├── port/out/event_enrichment_repository_port.py
│   ├── request/title_request.py
│   ├── response/{timeline_response.py, title_response.py}
│   ├── service/
│   │   ├── title_generation_service.py
│   │   └── text_utils.py                      (T2-3 신설)
│   └── usecase/{history_agent_usecase.py, generate_titles_usecase.py}
├── di.py                                      (T1-3 신설, FastAPI Depends 팩토리)
├── domain/entity/event_enrichment.py          (compute_detail_hash: constituent_ticker 선택 인자)
└── infrastructure/
    ├── orm/event_enrichment_orm.py
    └── mapper/event_enrichment_mapper.py

관련 신설:
app/domains/causality_agent/macro/
  └── run_macro_causality_agent.py             (T2-1 Phase B 스켈레톤)

app/domains/dashboard/adapter/outbound/external/
  └── yahoo_finance_etf_holdings_client.py    (T2-2 Step 2)

app/domains/dashboard/application/port/out/
  └── etf_holdings_port.py                     (T2-2 Step 2)

tests/domains/history_agent/application/
  ├── test_asset_type_dispatch.py              (T1-4)
  ├── test_index_causality_phase_a.py          (T2-1 Phase A)
  ├── test_etf_holdings.py                     (T2-2 Step 2)
  ├── test_text_utils.py                       (T2-3)
  ├── test_title_generation_service.py         (T1-1 / T2-4)
  └── test_event_dedup.py                      (T2-7)

tests/domains/causality_agent/macro/
  ├── fixtures/                                (Phase B 골든셋)
  └── test_golden_set.py                       (--eval 플래그 전용)
```

의존 방향: Adapter → Application → Domain. Domain은 순수 Python (`EventEnrichment`는 dataclass).

---

## 엔드포인트

prefix: `/history-agent`

| Method | Path | Handler | 비고 |
|---|---|---|---|
| GET | `/timeline` | `get_timeline` | 일괄 응답 |
| GET | `/timeline/stream` | `stream_timeline` | SSE: `progress`/`done`/`error` + 15s keepalive(`: ping`) + client disconnect 시 task cancel (T1-5) |
| POST | `/titles` | `generate_titles` | 배치 타이틀만, `GenerateTitlesUseCase` |
| GET | `/admin/fred/health` | `fred_series_health` | `_REGION_SERIES`의 각 FRED 시리즈를 3개월로 조회해 빈 시리즈 여부 확인 (T1-1) |

쿼리: `ticker`, `period ∈ {1D,1W,1M,1Y}`, `enrich_titles: bool`
`ticker`가 6자리 숫자면 `_resolve_corp_code()`로 DART `corp_code` 자동 조회.

DI: 라우터는 직접 인스턴스화 금지. `app/domains/history_agent/di.py`의 `get_history_agent_usecase` / `get_generate_titles_usecase` / `get_fred_macro_port` 를 `Depends(...)`로 연결 (T1-3).

---

## HistoryAgentUseCase.execute() 플로우

```
0. AssetTypePort.get_quote_type(ticker)                    ← 캐시 키에 포함하려고 먼저 수행 (T1-4)
     asset_type ∈ {EQUITY, INDEX, ETF, MUTUALFUND, CRYPTOCURRENCY, CURRENCY, UNKNOWN, ...}

0-1. cache_key = "history_agent:v2:{asset_type}:{ticker}:{period}[:no-titles]"   (T1-4)
     Redis GET (TTL 3600s). HIT → 즉시 반환.

0-2. 명시 dispatch:
     EQUITY → 아래 EQUITY 경로
     INDEX  → _execute_index_timeline()
     ETF    → _execute_etf_timeline()                       (T2-2, 더 이상 빈 응답 아님)
     기타(MUTUALFUND 등) → events=[] + asset_type=<원본값> + WARNING 1회  (T1-4)
```

### EQUITY 경로 (풀 파이프라인)

```
1. asyncio.gather(                                         ← 3개 병렬 수집
     GetPriceEventsUseCase(ticker, period),                # Yahoo OHLCV
     GetCorporateEventsUseCase(ticker, period, corp_code), # yfinance + DART
     GetAnnouncementsUseCase(ticker, period, corp_code),   # DART or SEC EDGAR
   )

2. _log_announcement_duplicates(timeline)                  ← T2-7: 같은 날 ANNOUNCEMENT Jaccard≥0.8
                                                             쌍을 WARNING으로만 로깅 (병합은 후속)

3. _load_enrichments → DB에서 (ticker, date, type, detail_hash) HIT
   HIT 분은 title/causality 즉시 주입, MISS만 new_events

4. asyncio.gather(                                         ← T1-2: 3-way 병렬
     _causality_then_price_titles(),   # causality → enrich_price_titles (가설 소비 때문에 직렬)
     enrich_other_titles(timeline),    # CORPORATE/ANNOUNCEMENT — causality 무관
     _enrich_announcement_details,     # 영문 공시(한글 無 AND ≥200자)만 한국어 요약 (T2-3)
   )
   enrich_titles=False면: PRICE는 rule_based_price_title만, 요약은 수행.

   _causality_then_price_titles():
     _enrich_causality(ticker, timeline, is_index=False)
       대상: category=PRICE ∧ type∈{SURGE,PLUNGE} ∧ causality is None, 상위 3건
       윈도우: event.date ±(-PRE_DAYS, +POST_DAYS)   # settings.history_causality_{pre,post}_days (T2-5)
       호출: causality_agent.run_causality_agent(...)
     → enrich_price_titles(is_index=False) (중요도 Top N만 LLM, 나머지 rule-based)

5. _save_enrichments(new_events) → PG upsert (detail_hash는 constituent_ticker 포함 가능, T2-2 Step 2)
6. Redis SET 캐시 (1h), asset_type="EQUITY"
```

SSE pct (EQUITY): `data_fetch=10`, `enrichment_load=35`, `causality=55`, `title_gen=75`, `saving=90`

### INDEX 경로 (`_execute_index_timeline`)

```
0. region = _INDEX_REGION.get(ticker, "US")
   ^IXIC/^GSPC/^DJI → "US" | ^KS11 → "KR" | 미지원 → "US"

1. asyncio.gather(                                         ← PRICE + MACRO 병렬 수집
     GetPriceEventsUseCase(ticker, period),                # Yahoo OHLCV
     GetEconomicEventsUseCase(period, region=region),      # FRED 시리즈 (리전 3개 병렬)
   )
   CORPORATE·ANNOUNCEMENT 수집 없음. MACRO 실패는 graceful degradation.

2. _load_enrichments / _apply_enrichments                  ← DB 캐시 동일 적용

3. _enrich_causality(is_index=True)                        ← T2-1 Phase A + (flag) Phase B
   Phase A: 근처 MACRO(±_INDEX_CAUSALITY_PRE/POST_DAYS)를 규칙 매핑 →
            HypothesisResult.supporting_tools_called=["fred:rule_based"]
   Phase B: settings.index_causality_llm_enabled=True일 때만,
            규칙 미매핑 케이스에 run_macro_causality_agent() 호출
            (골든셋 통과 전까지 False 고정)

4. asyncio.gather(
     enrich_price_titles(is_index=True),   ← INDEX_PRICE_TITLE_SYSTEM (매크로 관점)
     enrich_macro_titles,                  ← MACRO_TITLE_SYSTEM
   )

5. _save_enrichments → Redis SET 캐시 (1h), asset_type="INDEX"
```

SSE pct (INDEX): `data_fetch=10`, `title_gen=70`

### ETF 경로 (`_execute_etf_timeline`, T2-2)

```
0. region = _ETF_REGION.get(ticker, "US")
   SPY/QQQ/IWM/DIA/VOO/VTI/VEA/VWO → "US" | EWY/069500/229200 → "KR" | 미지원 → "US"

1. asyncio.gather(
     GetPriceEventsUseCase(ticker, period),                # ETF 자체 OHLCV
     GetEconomicEventsUseCase(period, region=region),      # 지역 MACRO
   )

2. Step 2 — holdings 분해 (etf_holdings_port 주입돼 있을 때만):
     _collect_holdings_events(etf_ticker, period):
       top_holdings(top_n=5) → 각 constituent에 대해
         asyncio.gather(GetCorporateEventsUseCase, GetAnnouncementsUseCase)
       반환 이벤트에 constituent_ticker, weight_pct 설정, source="{etf}:{origin}"
     holdings 이벤트를 타임라인에 병합.

3. _load_enrichments / _apply_enrichments
   (detail_hash = sha256(f"{constituent_ticker}|{detail}")[:16] — constituent별 분리)

4. asyncio.gather(
     enrich_price_titles(is_index=True),   # ETF도 매크로 관점 프롬프트
     enrich_macro_titles,
     enrich_other_titles,                  # constituent CORPORATE/ANNOUNCEMENT
     _enrich_announcement_details,
   )

5. _save_enrichments → Redis SET 캐시 (1h), is_etf=True, asset_type="ETF"
```

SSE pct (ETF): `data_fetch=10`, `constituents=40`, `title_gen=70`

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
  change_pct: Optional[float]                  # PRICE: 변화율(%) / MACRO: 이전 대비 변화폭(%p)
  causality: Optional[List[HypothesisResult]]  # INDEX: Phase A 규칙 / Phase B LLM이 채움 (T2-1)
  constituent_ticker: Optional[str] = None     # T2-2 Step 2 — ETF holdings 분해 시 채움
  weight_pct: Optional[float] = None           # T2-2 Step 2 — ETF holdings 비중 (0~100)

HypothesisResult: { hypothesis: str, supporting_tools_called: List[str] }
  # supporting_tools_called 값 예시:
  #   EQUITY causality_agent → ["get_fred_series", "get_price_stats", ...]
  #   INDEX Phase A           → ["fred:rule_based"]
  #   INDEX Phase B (LLM)     → ["llm:macro_causality", "fred:FEDFUNDS", ...]

TimelineResponse:
  ticker, period, count, events
  is_etf: bool = False                         # ETF일 때 True
  asset_type: str = "EQUITY"                   # 더 이상 Literal 아님 — 원본 yfinance quoteType
                                               # 그대로 전달될 수 있음 ("MUTUALFUND" 등)
```

---

## 이벤트 카테고리 × 타입

| Category | Types | 출처 Adapter | Asset Type |
|---|---|---|---|
| PRICE | `HIGH_52W`(응답에서 제외), `LOW_52W`, `SURGE`, `PLUNGE`, `GAP_UP`, `GAP_DOWN` | Yahoo OHLCV로 직접 계산 | EQUITY, INDEX, ETF |
| CORPORATE | `EARNINGS`, `DIVIDEND`, `STOCK_SPLIT`, `RIGHTS_OFFERING`, `BUYBACK`, `MANAGEMENT_CHANGE`, `DISCLOSURE` | `yfinance_corporate_port` + `DartCorporateEventClient` | EQUITY, ETF(constituents) |
| ANNOUNCEMENT | `MERGER_ACQUISITION`, `CONTRACT`, `MAJOR_EVENT` | `sec_edgar_port` 또는 `DartAnnouncementClient` | EQUITY, ETF(constituents) |
| MACRO | `INTEREST_RATE`, `CPI`, `UNEMPLOYMENT` | `GetEconomicEventsUseCase` → FRED API | INDEX, ETF |

`_EXCLUDED_PRICE_TYPES = {"HIGH_52W"}` (타임라인에서 제외)
`_PCT_VALUE_TYPES = {"SURGE","PLUNGE","GAP_UP","GAP_DOWN"}` (`e.value` → `change_pct`로 매핑)

MACRO `detail` 포맷 예: `"기준금리 5.25% (이전: 5.00%, 변화: +0.25%p)"`

---

## MACRO 이벤트 — FRED 시리즈 설정

`dashboard/.../get_economic_events_usecase.py`

### _SERIES_CONFIG (T1-1: 4-tuple로 확장)

`series_id → (event_type, label, apply_yoy, fallback_title)`

| Series ID | type | label | apply_yoy | fallback_title |
|---|---|---|---|---|
| `FEDFUNDS` | `INTEREST_RATE` | 기준금리 | False | 기준금리 결정 |
| `CPIAUCSL` | `CPI` | CPI | True (원지수 → YoY%) | CPI 발표 |
| `UNRATE` | `UNEMPLOYMENT` | 실업률 | False | 실업률 발표 |
| `INTDSRKRM193N` | `INTEREST_RATE` | 기준금리 (BOK) | False | 한국 기준금리 |
| `CPALTT01KRM657N` | `CPI` | CPI (한국) | True (원지수 → YoY%) | 한국 CPI 발표 |
| `LRHUTTTTKRIQ156S` | `UNEMPLOYMENT` | 실업률 (한국) | False | 한국 실업률 |

`macro_fallback_titles()` 함수가 `_SERIES_CONFIG`에서 `event_type → fallback_title` dict를 파생해
`title_generation_service.FALLBACK_TITLE`과 병합. MACRO fallback을 두 곳에 따로 적지 않아도 된다.

### _REGION_SERIES

```
"US": [FEDFUNDS, CPIAUCSL, UNRATE]
"KR": [INTDSRKRM193N, CPALTT01KRM657N, LRHUTTTTKRIQ156S]
# TODO: 글로벌 공통(유가 WTISPLC 등) 필요 시 "GLOBAL" 리전 추가
```

### _INDEX_REGION (`history_agent_usecase.py`)

```
^IXIC, ^GSPC, ^DJI  → "US"
^KS11               → "KR"
기타                 → "US" (default)
```

### _ETF_REGION (T2-2 Step 1)

```
SPY, QQQ, IWM, DIA, VOO, VTI, VEA, VWO   → "US"
EWJ                                       → "US"  (일본 ETF, 한국 MACRO 없음)
EWY, 069500 (KODEX 200), 229200           → "KR"
기타                                       → "US" (default)
```

### FRED 헬스 체크 (T1-1)

`GET /history-agent/admin/fred/health` 각 시리즈를 최근 3개월로 호출. 빈 시리즈는
`empty_series` 목록으로 반환되고 WARNING 로그. KR 시리즈 같은 deprecate 케이스를
조기 발견하기 위한 운영 도구.

---

## 타이틀 생성 (`title_generation_service.py`)

| 상수/설정 | 기본값 | 런타임 override (T2-5) |
|---|---|---|
| `TITLE_MODEL` | `"gpt-5-mini"` | — (코드 상수) |
| `TITLE_BATCH` | 15 | `settings.history_title_batch_size` |
| `TITLE_CONCURRENCY` | 10 | `settings.history_title_concurrency` |
| `PRICE_LLM_TOP_N` | 50 | `settings.history_price_llm_top_n` |
| causality pre-window | 14일 | `settings.history_causality_pre_days` |
| causality post-window | 3일 | `settings.history_causality_post_days` |
| INDEX Phase B 활성화 | False | `settings.index_causality_llm_enabled` |

`price_importance(e)` 점수:
- `abs(change_pct)`
- `+100` if `causality` 있음
- `+50` if type ∈ {SURGE, PLUNGE}
- `+30` if type = LOW_52W
- `+5` if type ∈ {GAP_UP, GAP_DOWN}

→ 상위 N건만 LLM. 나머지는 `rule_based_price_title()` (예: `"급등 (+5.2%)"`).

**시스템 프롬프트**

| 상수 | 적용 대상 | 특징 |
|---|---|---|
| `PRICE_TITLE_SYSTEM` | EQUITY PRICE | 15자, 개별 기업 원인·배경 중심 |
| `INDEX_PRICE_TITLE_SYSTEM` | INDEX / ETF PRICE | 15자, 거시경제·섹터·정책 요인 중심 |
| `MACRO_TITLE_SYSTEM` | MACRO | 15자, 지표 방향·의미 중심 (동결/완화/상회 등) |
| `OTHER_TITLE_SYSTEM` | CORPORATE·ANNOUNCEMENT | 12자 |

모두 JSON 배열 응답, 이벤트 순서 일치 필수.

`is_fallback_title(event)` — `FALLBACK_TITLE` 매핑값과 일치 여부로 미생성 판별.

**FALLBACK_TITLE 구성 (T1-1)**

- `_NON_MACRO_FALLBACK` (모듈 상수) + `macro_fallback_titles()` 병합
- MACRO 파트는 `get_economic_events_usecase._SERIES_CONFIG`에서 파생 — 시리즈 추가/변경 시
  한 곳(`_SERIES_CONFIG`)만 수정.
- `default_fallback(item)`: type이 dict에 없으면 `item.label`이 있으면 label, 아니면 raw type.

**LLM 배치 에러 처리 (T2-4, `batch_titles`)**

- `_classify_error(exc)` → `"timeout" | "json" | "rate_limit" | "other"`
- **JSON 파싱 실패** → 시스템 프롬프트에 "JSON 배열만" 지시 append 후 **1회 재시도**
- **Rate limit** (`RateLimit*/Throttling*/TooManyRequests*` 클래스 이름 감지) → 지수 backoff **(1s, 2s)** 최대 2회
- **Timeout / 기타** → 재시도 없이 fallback
- 배치마다 `time.monotonic()` 지연 측정 → 완료 시 `failures` 카운트 + `latency_p50`/`p95` 로그

---

## 캐시 이중 구조

### L1 — Redis (응답 단위)
- Key: `history_agent:v2:{asset_type}:{ticker}:{period}` (+ `:no-titles` if `enrich_titles=False`) (T1-4)
  - `v2` 프리픽스로 구 포맷 캐시 자동 무효화
  - `asset_type` 포함 → yfinance가 티커를 재분류해도 stale cache 방지
- Value: `TimelineResponse` JSON (MACRO 이벤트, constituent 필드 포함)
- TTL: 3600s (`_CACHE_TTL`)

### L2 — PostgreSQL `event_enrichments` (이벤트 단위, 영구)
Unique: `(ticker, event_date, event_type, detail_hash)`
- `detail_hash = sha256(f"{constituent_ticker}|{detail}" if constituent_ticker else detail)[:16]` (T2-2 Step 2)
  - constituent가 다르면 같은 detail이라도 서로 다른 row로 저장
  - ETF 내 AAPL의 이벤트와 QQQ 내 AAPL의 이벤트는 `ticker`(ETF)와 `constituent_ticker`가 달라 충돌 없음
- MACRO 이벤트도 동일 키 구조로 저장됨 (ticker=지수/ETF 코드, type=INTEREST_RATE 등)
- Columns: `title: Text`, `causality: JSONB`, `created_at`, `updated_at`
- Upsert: `ON CONFLICT … DO UPDATE` set `title, causality, updated_at`
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
| `dashboard...EtfHoldingsPort` (T2-2) | `YahooFinanceEtfHoldingsClient` | ETF 상위 보유 종목 + 비중 |
| `history_agent...EventEnrichmentRepositoryPort` | `EventEnrichmentRepositoryImpl` | enrichment 영구 캐시 |

DI (T1-3): 라우터는 수동 인스턴스화 금지. `app/domains/history_agent/di.py`에서
`@lru_cache(maxsize=1)` 모듈 싱글톤으로 stateless 클라이언트를 재사용하고
FastAPI `Depends`로 주입한다.

---

## 주요 상수 (usecase 레벨)

```
_CACHE_TTL                        = 3600           # Redis 초
_CACHE_VERSION                    = "v2"           # T1-4 — asset_type 포함 키 전환
_SUPPORTED_ASSET_TYPES            = {EQUITY, INDEX, ETF}

_CAUSALITY_TRIGGER_TYPES          = {SURGE, PLUNGE}   # 계약 — settings로 이동 안 함
_MAX_CAUSALITY_EVENTS             = 3
# _CAUSALITY_PRE_DAYS / _CAUSALITY_POST_DAYS 는 settings.history_causality_{pre,post}_days 로 이동 (T2-5)
_INDEX_CAUSALITY_PRE_DAYS         = 3              # Phase A MACRO 매핑 윈도우
_INDEX_CAUSALITY_POST_DAYS        = 1

_EXCLUDED_PRICE_TYPES             = {HIGH_52W}
_PCT_VALUE_TYPES                  = {SURGE, PLUNGE, GAP_UP, GAP_DOWN}

_INDEX_REGION                     = {^IXIC/^GSPC/^DJI→"US", ^KS11→"KR"}
_DEFAULT_INDEX_REGION             = "US"
_ETF_REGION                       = {SPY/QQQ/IWM/...→"US", EWY/069500/...→"KR"}   # T2-2

# 공시 중복 탐지 (T2-7 — 로깅만)
_ANNOUNCEMENT_SOURCE_PRIORITY     = {DART:0, SEC:1, SEC_EDGAR:1, YAHOO:2}
_ANNOUNCEMENT_DEDUP_THRESHOLD     = 0.8            # Jaccard
```

한글/영문 판별: `application/service/text_utils.py::needs_korean_summary(text)` (T2-3)
- Hangul 블록(`\uAC00-\uD7A3`)이 하나라도 포함되면 요약 skip
- 순수 비한글 ∧ 길이 ≥ 200자만 한국어 요약 LLM 호출
- 구 `_is_english_text` 휴리스틱(ASCII 60%)은 폐기됨

---

## 수정 포인트 치트시트

| 하고 싶은 일 | 건드릴 파일·심볼 |
|---|---|
| 새 지수 → 리전 추가 (예: ^N225 → JP) | `history_agent_usecase._INDEX_REGION` + `_REGION_SERIES["JP"]` 시리즈 추가 |
| 새 ETF → 리전 추가 | `history_agent_usecase._ETF_REGION` 항목 추가 |
| 글로벌 이벤트(유가 등) 전 지수 공통 노출 | `_REGION_SERIES` "GLOBAL" 리전 추가 + `_execute_index_timeline` / `_execute_etf_timeline`에서 US+GLOBAL 병합 |
| KR MACRO 시리즈 교체 | `get_economic_events_usecase._SERIES_CONFIG` — fallback_title까지 포함해 수정 |
| INDEX에 CORPORATE 이벤트 추가 | `_execute_index_timeline` — corporate_uc 추가 |
| INDEX Phase B LLM 활성화 | golden-set 30건 통과 확인 후 `settings.index_causality_llm_enabled=True` |
| Phase B 프롬프트/컨텍스트 수정 | `app/domains/causality_agent/macro/run_macro_causality_agent.py` |
| Phase A 규칙 윈도우 조정 | `_INDEX_CAUSALITY_PRE_DAYS`, `_INDEX_CAUSALITY_POST_DAYS` |
| INDEX PRICE 타이틀 프롬프트 변경 | `title_generation_service.INDEX_PRICE_TITLE_SYSTEM` |
| MACRO 타이틀 프롬프트 변경 | `title_generation_service.MACRO_TITLE_SYSTEM` |
| EQUITY PRICE 타이틀 프롬프트 변경 | `title_generation_service.PRICE_TITLE_SYSTEM` |
| 새 PRICE 이벤트 타입 추가 | `dashboard` 도메인의 PRICE 탐지 로직 + `_NON_MACRO_FALLBACK` + `_PCT_VALUE_TYPES` |
| 새 MACRO 시리즈 추가 | `_SERIES_CONFIG` 에 `(event_type, label, apply_yoy, fallback_title)` 추가 — `FALLBACK_TITLE`은 자동 파생 |
| causality 대상 확장 | `_CAUSALITY_TRIGGER_TYPES`, `_MAX_CAUSALITY_EVENTS` |
| 타이틀 LLM 개수 조정 | `settings.history_title_batch_size`, `history_title_concurrency`, `history_price_llm_top_n` (env/config) |
| causality 윈도우 조정 | `settings.history_causality_{pre,post}_days` |
| 캐시 TTL | `_CACHE_TTL` |
| 캐시 무효화 (대규모) | `_CACHE_VERSION`을 `v3` 등으로 bump |
| LLM 배치 에러 재시도 로직 변경 | `title_generation_service._classify_error`, `batch_titles` |
| 새 공시 소스 추가 | `GetAnnouncementsUseCase` (`dashboard` 도메인) + `di.py` 싱글톤 추가 |
| 영문→한글 요약 프롬프트 | `_ANNOUNCEMENT_SUMMARY_SYSTEM` (history_agent_usecase.py) |
| 영문 감지 기준 변경 | `text_utils._MIN_LEN_FOR_ENGLISH_SUMMARIZATION` 또는 `needs_korean_summary` 로직 |
| ETF holdings 수 변경 | `_collect_holdings_events` `top_n` 인자 (기본 5) |
| 새 외부 클라이언트 주입 | `di.py`에 `@lru_cache(maxsize=1)` 팩토리 + `HistoryAgentUseCase` 생성자 인자 추가 |
| 공시 중복 병합 로직 활성화 | `_log_announcement_duplicates` → 실제 merge 경로로 교체 (T2-7 후속 작업) |

---

## 관련 외부 도메인

- **`dashboard`** — 모든 데이터 수집 UseCase (`GetPriceEventsUseCase`, `GetCorporateEventsUseCase`, `GetAnnouncementsUseCase`, `GetEconomicEventsUseCase`)와 외부 API 클라이언트 전부 여기 있음. `EtfHoldingsPort` + `YahooFinanceEtfHoldingsClient`도 T2-2로 여기 추가됨.
- **`causality_agent`** — `causality_agent_workflow.run_causality_agent(ticker, start_date, end_date)` 호출 (lazy import). T2-1 Phase B로 `causality_agent.macro.run_macro_causality_agent` 가 INDEX 전용으로 추가됨.
- **`disclosure`** — `CompanyRepositoryImpl.find_by_stock_code(ticker)` 로 DART `corp_code` 조회.

---

## 검증 안 된 가정 (변경 전 확인 필요)

- `period` → 실제 조회 기간 변환 로직 — `dashboard`의 각 UseCase 내부
- causality workflow의 반환 shape — `causality_agent.application.causality_agent_workflow`
- `AssetTypePort.get_quote_type()` 반환값이 yfinance `"MUTUALFUND"` / `"CRYPTOCURRENCY"` 등일 때 **T1-4부터는 빈 응답 반환**으로 동작 변경됨. 이전에는 UNKNOWN → EQUITY 풀 파이프라인이었음.
- INDEX 티커 중 yfinance가 `"INDEX"` 대신 다른 quoteType을 반환하는 케이스 존재 여부 — 실 호출 로그로 확인 필요
- KR FRED 시리즈 실존 여부 — `INTDSRKRM193N`, `CPALTT01KRM657N`, `LRHUTTTTKRIQ156S` 가 실제 FRED에 존재하는지 `/history-agent/admin/fred/health` 로 조기 확인 가능 (T1-1)
- `CPALTT01KRM657N` 가 index level 시리즈인지 이미 % change 시리즈인지 — `apply_yoy=True` 설정 기준으로 잡혔으나 시리즈 특성 재확인 필요
- yfinance `Ticker.funds_data.top_holdings` — VTI처럼 보유 500+개 ETF도 상위 5만 반환되는지, 비중 단위가 0~1인지 0~100인지 실 호출로 확인 필요 (구현은 0~1 → %로 변환)
- Phase B LLM 프롬프트 품질 — 30건 골든셋이 아직 `sample_01.json` 하나만 존재. 나머지 29건은 런칭 전 수동 라벨링 필요.

---

## Recent Changes

2026-04-20 Tier 1 + Tier 2 스프린트 완료. 주요 변경:

### Tier 1 — 기반 정리
- **T1-1 · MACRO fallback 일원화**: `_SERIES_CONFIG`가 `(event_type, label, apply_yoy, fallback_title)` 4-tuple로 확장. `macro_fallback_titles()`로 `FALLBACK_TITLE` MACRO 엔트리 자동 파생. `/history-agent/admin/fred/health` 엔드포인트 추가.
- **T1-2 · 파이프라인 병렬화**: EQUITY `execute()`에서 causality→price_titles 와 other_titles / announcement_details를 `asyncio.gather`로 병렬 실행. 비-PRICE 이벤트 타이틀 생성이 causality 완료를 기다리던 직렬화 제거.
- **T1-3 · DI 모듈**: `app/domains/history_agent/di.py` 신설. 라우터에서 6개+ 외부 클라이언트 직접 인스턴스화 제거. stateless 클라이언트는 `@lru_cache(maxsize=1)`로 모듈 싱글톤 재사용. CLAUDE.md 규칙 준수.
- **T1-4 · asset_type 명시 dispatch + 캐시 키**: EQUITY/INDEX/ETF만 본선 처리, MUTUALFUND/CRYPTO/UNKNOWN 등은 명시적으로 빈 응답 + WARNING. Redis 키에 `v2:{asset_type}:` 추가해 재분류 시 stale cache 방지.
- **T1-5 · SSE 정합성**: 15초 keepalive(`: ping`) 프레임, 클라이언트 disconnect 시 `_run` 태스크 `task.cancel()`, `on_progress` 콜백 예외 로깅.

### Tier 2 — 기능 확장
- **T2-1 Phase A · INDEX causality 규칙 기반**: `_infer_rule_based_index_causality(event, macro_events)` — ±3/+1일 내 MACRO 발표를 "MACRO 방향(Δ..%p, D..) → PRICE 타입" 형식 가설로 매핑. `supporting_tools_called=["fred:rule_based"]`.
- **T2-1 Phase B · INDEX causality LLM (feature flag)**: `app/domains/causality_agent/macro/run_macro_causality_agent.py` 스켈레톤. 규칙 미매핑 케이스에만 LLM 호출. `settings.index_causality_llm_enabled=False`로 기본 차단. `tests/domains/causality_agent/macro/fixtures/`에 골든셋 30건 필요 (현재 1건 + README).
- **T2-2 Step 1 · ETF 베이스 커버**: `_execute_etf_timeline` 신설. `_ETF_REGION`으로 US/KR 매핑. ETF는 더 이상 빈 응답이 아니라 PRICE + 지역 MACRO 반환.
- **T2-2 Step 2 · ETF holdings 분해**: `TimelineEvent`에 `constituent_ticker`, `weight_pct` 추가. `EtfHoldingsPort` + `YahooFinanceEtfHoldingsClient` 신설. `_collect_holdings_events`가 top-5 보유 종목의 CORPORATE/ANNOUNCEMENT 병렬 수집. `detail_hash`가 `constituent_ticker`를 포함해 충돌 방지. 프론트 `LazyTimelineEventCard`에 constituent 뱃지 + weight 툴팁 추가.
- **T2-3 · 한글 감지 교체**: `text_utils.needs_korean_summary` — Hangul 블록 포함 여부 기반. 한글 1자라도 있으면 요약 skip, 순수 영문 ≥200자만 LLM. 구 `_is_english_text`(ASCII 60%) 폐기.
- **T2-4 · LLM 에러 분류·재시도**: `_classify_error(exc)`가 timeout/json/rate_limit/other로 분류. JSON 실패는 "JSON 배열만" 지시 append 후 1회 재시도, rate_limit는 1s/2s backoff 최대 2회. 배치별 p50/p95 지연 로깅.
- **T2-5 · 튜닝 env 이관**: `TITLE_BATCH/CONCURRENCY/PRICE_LLM_TOP_N/_CAUSALITY_PRE_DAYS/_CAUSALITY_POST_DAYS` 를 `settings.history_*`로 이동. `index_causality_llm_enabled` 플래그 추가.
- **T2-6 · 테스트 보강**: `test_text_utils.py`, `test_title_generation_service.py`, `test_asset_type_dispatch.py`, `test_index_causality_phase_a.py`, `test_etf_holdings.py`, `test_event_dedup.py` 추가. 히스토리 에이전트 관련 테스트 28 → 64 (+36).
- **T2-7 · 공시 중복 로깅**: `_jaccard_similarity` + `_log_announcement_duplicates`로 같은 날 ANNOUNCEMENT 유사도 ≥0.8 쌍을 WARNING 로깅. 실제 병합(`_ANNOUNCEMENT_SOURCE_PRIORITY` 기반 선택)은 운영 로그 검증 후 활성화 예정.

### 아직 남은 Tier 2 후속 작업
- Phase B 골든셋 29건 수동 라벨링 → `settings.index_causality_llm_enabled=True` 전환
- T2-7 실제 병합 경로 활성화 (우선 로그만 수집)
- T3-1 observability (per-stage duration, cache hit counter 등)는 Tier 3으로 보류

---

2026-04-21 **데이터 소스 확장 스프린트 (Tier A/B/C)** — 뉴스 0% 커버리지 해소 + yfinance 429 내성.

### Tier A — 현 소스 429 내성 강화
- **A-1 · yfinance 공통 retry 래퍼**: `dashboard/adapter/outbound/external/_yfinance_retry.py::yfinance_call_with_retry`. 429(YFRateLimitError/HTTP 429)·ConnectionError·Timeout만 지수 backoff(1s/2s/4s) 재시도, 도메인 예외는 즉시 전파. 적용 대상: `YahooFinanceStockClient`, `YahooFinanceCorporateEventClient`, `YahooFinanceAssetTypeClient`, `YahooFinanceEtfHoldingsClient`. 설정: `yfinance_retry_max_attempts`(3), `yfinance_retry_base_delay`(1.0).
- **A-2 · ETF holdings 팬아웃 세마포어**: `_collect_holdings_events`의 5-way fan-out이 yfinance/DART/SEC에 최대 10 동시 요청을 발사하던 문제를 `asyncio.Semaphore(settings.history_holdings_concurrency)`(기본 3)로 제한.
- **A-3 · asset_type 24h 장기 캐시**: `CachedAssetTypeAdapter`가 기존 `YahooFinanceAssetTypeClient`를 감싸 L1 프로세스 로컬 dict + L2 Redis(`asset_type:{ticker}`, TTL 86400s) 2중 캐시 제공. UNKNOWN은 Redis에 저장하지 않아 오분류 고착 방지. DI에서 요청마다 주입해 Redis 인스턴스는 사용자 요청별 유지.

### Tier B — 뉴스 커버리지 (기존 causality_agent 클라이언트 재사용)
- **B-1 · NewsEventPort + CompositeNewsProvider**: `application/port/out/news_event_port.py`에 `NewsItem`(date/title/url/source/summary/sentiment) + `NewsEventPort.fetch_news(ticker, period, region, top_n)` 정의. `adapter/outbound/composite_news_provider.py`가 region별 fail-over 체인을 구현:
  - `US`: Finnhub → GDELT → Yahoo
  - `KR`: Naver → GDELT → Yahoo
  - `GLOBAL` (INDEX/ETF): GDELT(`_INDEX_KEYWORDS` 매핑 키워드) → Finnhub → Yahoo
  
  **성공한 상위 소스에서 결과를 얻으면 하위 소스는 호출하지 않는다** — 429 감축 최우선 설계. 각 소스는 `asyncio.wait_for(..., timeout=settings.history_news_per_source_timeout_s)`(기본 8s)로 감싸 지연 소스가 전체 요청을 막지 않게 한다. 최종 결과는 `_dedup`(일자 + Jaccard ≥0.8)로 중복 제거.
- **B-2 · TimelineEvent `NEWS` 카테고리**: `TimelineEvent.category`에 `"NEWS"`가 추가되고 `sentiment: Optional[float]` 필드 신설. `source`는 `f"news:{provider}"`(예: `news:finnhub`) 형식으로 UI에서 뱃지 매핑 가능. 타이틀은 원문 기사 제목을 그대로 사용해 LLM 재생성 비용 없음. `FALLBACK_TITLE`에 `"NEWS": "뉴스"` 추가.
- **B-3 · execute 경로 병렬 통합 + 캐시 버전 v3**: EQUITY/INDEX/ETF 모두 `asyncio.gather`에 `_collect_news_events(ticker, period, region)` 추가. 캐시 키 `_CACHE_VERSION`을 `v2` → `v3` 로 bump해 이전 스키마 캐시 무효화. EQUITY region은 `_resolve_equity_region`(6자리 숫자 → KR, 그 외 US)로 판정.
- **B-4/B-5 · scrape + causality context**: 현재 스코프에서는 구조만 준비(feature flag `history_news_scrape_enabled` 기본 false). 본문 요약 · causality 워크플로우에 NewsItem 주입은 다음 이터레이션.

### Tier C — Non-news 신규 소스
- **C-2 · Finnhub 애널리스트/실적**: `FinnhubNewsClient`에 `get_recommendation_trend`, `get_earnings_surprise` 메서드 추가. `FinnhubFundamentalsAdapter`(`adapter/outbound/finnhub_fundamentals_adapter.py`)가 월별 buy 비율 차이가 ±10%p 이상이면 `ANALYST_UPGRADE/DOWNGRADE`, 실적 surprise% 절대값 ≥2%면 `EARNINGS_BEAT/MISS` 이벤트로 승격. CORPORATE 카테고리 아래로 들어간다. EQUITY 경로에만 활성.
- **C-3 · RelatedAssets + GPR 배선**: `RelatedAssetsAdapter`가 VIX/WTI/Gold/UST10Y/JPYUSD 일간 변동이 `history_related_assets_threshold_pct`(기본 2%) 이상인 날을 `VIX_SPIKE/OIL_SPIKE/...` 로 승격. `GprIndexAdapter`는 전월 대비 GPR 지수가 `history_gpr_mom_change_pct`(기본 20%) 이상 상승한 달을 `GEOPOLITICAL_RISK` 로 승격. 둘 다 MACRO 카테고리. INDEX/ETF 경로에서만 `_collect_macro_context`로 병렬 수집.

### 신규/갱신 파일
- 신규: `_yfinance_retry.py`, `cached_asset_type_adapter.py`, `composite_news_provider.py`, `news_event_port.py`, `finnhub_fundamentals_adapter.py`, `fundamentals_event_port.py`, `macro_context_adapter.py`, `related_assets_port.py`
- 갱신: `finnhub_news_client.py` (+레이팅/실적), `history_agent_usecase.py` (+3 수집 메서드 + 경로 통합), `di.py` (+4 포트 주입), `title_generation_service.py` (+11 타입 fallback), `timeline_response.py` (+sentiment, 카테고리 주석), `settings.py` (+8 튜닝 키), `CLAUDE.md`

### 신규 테스트 (33개 추가 → 총 96개 통과)
- `tests/domains/history_agent/application/test_composite_news_provider.py` — fail-over, timeout, KR/US/GLOBAL 분기, Jaccard dedup (9건)
- `tests/domains/history_agent/adapter/test_yfinance_retry.py` — 429 분류, backoff 지수, 도메인 예외 전파 (10건)
- `tests/domains/history_agent/adapter/test_cached_asset_type.py` — L1/L2 캐시, UNKNOWN skip (5건)
- `tests/domains/history_agent/adapter/test_finnhub_fundamentals_adapter.py` — 레이팅/실적 threshold (5건)
- `tests/domains/history_agent/adapter/test_macro_context_adapter.py` — RelatedAssets/GPR threshold (4건)

### 설정 (신규)
| 키 | 기본 | 의미 |
|---|---|---|
| `history_holdings_concurrency` | 3 | ETF holdings 팬아웃 동시성 상한 |
| `history_news_top_n` | 10 | 뉴스 이벤트 최대 건수 |
| `history_news_per_source_timeout_s` | 8.0 | 뉴스 소스별 타임아웃 |
| `history_news_scrape_enabled` | false | 뉴스 본문 스크랩+요약 활성화 (B-4 차기) |
| `history_related_assets_threshold_pct` | 2.0 | VIX/oil/gold 이벤트 승격 임계 |
| `history_gpr_mom_change_pct` | 20.0 | GPR 전월 대비 상승 임계 |
| `yfinance_retry_max_attempts` | 3 | yfinance 재시도 최대 횟수 |
| `yfinance_retry_base_delay` | 1.0 | yfinance backoff 기본 지연(s) |

### 남은 후속 작업
- B-4 · `ArticleContentScraper` 연동으로 상위 N개 뉴스 본문 요약(`history_news_scrape_enabled=true`시).
- B-5 · causality 워크플로우(`run_causality_agent`, `run_macro_causality_agent`) 시그니처에 `context_news: List[NewsItem]` 추가해 중복 뉴스 호출 제거.
- KR 뉴스 검색 시 티커(6자리 숫자) → 회사명 매핑 — 현재는 ticker 자체를 Naver 검색어로 사용.
- C-1 · SEC Form 4 내부자 거래 (별도 스프린트).
- Tier 3 (observability 메트릭) — 운영 로그 축적 후 재평가.
