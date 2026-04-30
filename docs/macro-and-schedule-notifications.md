# Macro Dashboard + Schedule Notifications — 기능 요약

> Antelligen Backend의 두 핵심 사용자 기능: **거시 경제 현황판** 과 **경제일정 알림**

---

## 1. 한눈에

| 기능 | 도메인 | 역할 |
|------|--------|------|
| **거시 경제 현황판** | `macro/` | 시장 리스크(Risk-on / Risk-off) 즉시 응답 — 일 1회 LLM 갱신 + 메모리/Redis 캐시 |
| **경제일정 알림** | `schedule/` | 경제 일정 LLM 영향 분석이 저장될 때마다 DB 기록 + SSE 실시간 푸시 |

두 기능은 **매크로 지표 스냅샷**(금리·유가·환율·VIX·DXY·지수·금 등 13종)을 공유하며, 거시 현황판의 contextual 판단과 경제일정 영향 분석이 **같은 데이터 기반**으로 상호 강화됩니다.

---

## 2. 거시 경제 현황판 (Macro Dashboard)

### 2.1 무엇인가

매일 새벽 1시 LLM 파이프라인이 학습 노트 + YouTube 영상 + 월가 IB 페르소나 분석을 종합해 **시장 리스크 판단**을 내린 뒤, 메모리/Redis 캐시에 적재. 프론트는 캐시된 스냅샷을 즉시 받아 본다.

### 2.2 핵심 흐름

```
APScheduler (01:00 daily, macro_jobs.py:30)
       │
       ▼
JudgeMarketRiskUseCase.execute()
       │
       ├─▶ StudyNoteFileReader      (학습 노트 파일)
       ├─▶ YoutubeMacroVideoClient   (Antelligen 채널 최근 7일)
       └─▶ LangchainRiskJudgement    (OpenAI GPT)
              │
              ├─ contextual: 학습/영상 기반 판단
              └─ baseline:   월가 IB 페르소나 판단
       │
       ▼
MarketRiskSnapshotStore  (메모리 + Redis TTL 25h)
       │
       ▼
GET /api/v1/macro/market-risk  →  즉시 응답
```

### 2.3 데이터 소스

| 소스 | 용도 | 위치 |
|------|------|------|
| 로컬 학습 노트 | contextual 판단 근거 | `StudyNoteFileReader` |
| YouTube Data API | 참고 영상 4건 (Antelligen 채널 `UC2-YdiOkgqWzIdDwCYW1utw`, 최근 7일) | `youtube_macro_video_client.py` |
| OpenAI GPT | 듀얼 판단 생성 | `langchain_risk_judgement_adapter.py:8-14` |

### 2.4 응답 구조

`MarketRiskJudgementResponse`

| 필드 | 의미 |
|------|------|
| `status` | 최종 판단 — `RISK_ON` / `RISK_OFF` / `UNKNOWN` |
| `contextual_status` + `contextual_reasons[3]` | 학습 노트·영상 기반 판단 (3줄 근거) |
| `baseline_status` + `baseline_reasons[3]` | 월가 IB 페르소나 판단 (3줄 근거) |
| `reference_videos[]` | YouTube 영상 메타 (id, title, published_at, url) |
| `note_available` | 학습 노트 존재 여부 |
| `updated_at` | 스냅샷 갱신 시각 |

### 2.5 캐시 전략

- **메모리**: `MarketRiskSnapshotStore` — 스레드-세이프 프로세스 싱글톤
- **Redis**: TTL 25h (`MACRO_SNAPSHOT_REDIS_TTL_SECONDS`, `macro_jobs.py:26-27`)
- **Hot reload 안전**: 프로세스 재시작 시 Redis에서 직전 스냅샷 복원 → YouTube/LLM 재호출 회피

### 2.6 라우트

```
GET /api/v1/macro/market-risk  →  BaseResponse[MarketRiskJudgementResponse]
```

### 2.7 주목할 패턴

1. **이중 판단(contextual + baseline)**
   학습 노트 기반 판단과 일반 IB 페르소나 판단을 **분리 노출** → 프론트가 사용자에게 어느 쪽을 보여줄지 선택 가능
2. **출처 표기 일원화**
   모든 응답을 "Antelligen AI 자체 분석" 으로 표기. 유튜브 채널명·영상명·외부 리서치 기관명은 절대 노출 금지 (`langchain_risk_judgement_adapter.py:37-40`)

---

## 3. 경제일정 알림 (Schedule Notifications)

### 3.1 무엇인가

경제 일정의 LLM 영향 분석이 새로 저장될 때마다 **DB 알림 row를 기록** + **SSE로 실시간 푸시**. 프론트는 종모양 알림 UI에서 미읽음 카운트와 카드 목록을 받아 본다.

### 3.2 핵심 흐름

```
POST /schedule/event-analysis/run
       │  (또는 GET /event-analysis 가 lazy 트리거)
       ▼
RunEventImpactAnalysisUseCase.execute()
       │
       ├─▶ 경제 일정 조회 (DB)
       ├─▶ 매크로 지표 스냅샷  (FRED + Yahoo)
       └─▶ OpenAIEventImpactAnalyzer  (LLM 분석)
       │
       ▼
ScheduleNotificationPublisher.publish()
       ├─▶ schedule_notifications row INSERT  (DB)
       └─▶ NotificationBroadcaster.publish()  (asyncio.Queue → SSE)
       │
       ▼
GET /schedule/notifications/stream  (구독자에게 실시간 푸시)
```

### 3.3 트리거

- **명시적**: `POST /api/v1/schedule/event-analysis/run`
- **암시적(lazy)**: `GET /api/v1/schedule/event-analysis` (`schedule_router.py:314-319`)

### 3.4 저장 스키마

`schedule_notifications` (`schedule_notification_orm.py:9-28`)

| 컬럼 | 타입 | 비고 |
|------|------|------|
| `id` | PK / autoincrement | |
| `event_id` | FK → `economic_events.id` | |
| `event_title` | VARCHAR(255) | 일정 제목 스냅샷 |
| `analysis_id` | FK nullable | 분석 row 참조 |
| `success` | BOOLEAN | 분석 성공/실패 |
| `stored_at` | DATETIME | 분석 저장 시각 |
| `error_message` | TEXT | 실패 시 메시지 |
| `read_at` | DATETIME nullable | 읽음 처리 시각 |
| `created_at` | DATETIME | 알림 생성 시각 |

인덱스: `(read_at, created_at)`, `(event_id)`

### 3.5 API 엔드포인트

| Method | Path | 역할 | UseCase |
|--------|------|------|---------|
| GET | `/schedule/notifications` | 목록 조회 (`limit`, `unread_only`) | `ListScheduleNotificationsUseCase` |
| POST | `/schedule/notifications/{id}/read` | 개별 읽음 | `MarkScheduleNotificationReadUseCase.execute_single()` |
| POST | `/schedule/notifications/read-all` | 전체 읽음 | `.execute_all()` |
| GET | `/schedule/notifications/stream` | **SSE 실시간 구독** | broadcaster 직결 |

### 3.6 실시간 푸시 (SSE Broadcaster)

`notification_broadcaster.py:14-57`

- **방식**: 인-프로세스 `asyncio.Queue` 기반 pub/sub (싱글톤)
- **구독**: `GET /stream` 호출 시 큐 1개 할당 → 리스트 등록
- **발행**: `Publisher.publish()` 가 모든 큐에 페이로드 fan-out
- **Keepalive**: 30초마다 `: keep-alive\n\n` 주석 라인 (`schedule_router.py:436`)
- **페이로드**: JSON (id, event_id, event_title, success, stored_at, read_at)

> **주의**: 단일 프로세스 메모리 기반 — uvicorn 워커 ≥ 2 시 **워커 간 공유 안됨**.
> 멀티 워커가 필요하면 Redis Pub/Sub 또는 외부 브로커로 교체 필요.

### 3.7 읽음 상태 처리

- 단건: `ScheduleNotificationRepositoryImpl.mark_read(id)` → `read_at = now` UPDATE
- 일괄: `mark_all_read()` → `WHERE read_at IS NULL` 단일 SQL UPDATE
- (`schedule_notification_repository_impl.py:52-75`)

### 3.8 분석 입력 — 매크로 스냅샷 13종

`run_event_impact_analysis_usecase.py:128-146`

```
INTEREST_RATE (DGS10) · US_T2Y · US_T20Y
OIL_PRICE (WTI) · GOLD
EXCHANGE_RATE (USD/KRW) · USD_JPY · DXY
VIX
SP_500 · NASDAQ_100 · KOSPI_200
```

- **공급자**: Composite — FRED 1순위, Yahoo 폴백 (`search_investment_info_usecase.py:55-59`)
- 같은 13종이 LLM 프롬프트 컨텍스트에 그대로 주입됨

### 3.9 주목할 패턴

1. **저장과 푸시 분리**
   DB INSERT 실패해도 SSE 브로드캐스트는 최선 노력으로 수행 (`schedule_notification_publisher_impl.py:39-65`)
2. **이벤트 collapse**
   같은 `(country, date)` 의 FOMC 동의어 패턴은 **1건으로 collapse** (`run_event_impact_analysis_usecase.py:79-121`) — 화면 중복 방지
3. **응답 라벨 충돌 해소**
   같은 `(title, country)` 가 윈도우에 2건 이상 들어오면 ` (M/D)` suffix 추가 (`annotate_duplicate_titles`) — 한 release가 월 2회 발표(예: Chicago Fed CARTS) 케이스 대응

---

## 4. 두 기능의 협력

```
┌─────────────────────────────────────────────────────┐
│  Macro Dashboard                                    │
│  - 학습 노트 + YouTube + LLM                         │
│  - 매크로 지표 13종 스냅샷                            │
│  - Risk-on / Risk-off 판단                          │
└──────────────────┬──────────────────────────────────┘
                   │ 매크로 지표 스냅샷 공유
                   ▼
┌─────────────────────────────────────────────────────┐
│  Schedule Notifications                             │
│  - 같은 13종 지표를 LLM 프롬프트에 주입              │
│  - 경제 일정의 영향(direction · key_drivers · risks)│
│  - DB 알림 + SSE 푸시                               │
└─────────────────────────────────────────────────────┘
```

- 거시 현황판의 **contextual Risk** 판단과 경제일정 영향 분석이 동일 데이터 기반 → 사용자가 보는 "오늘의 시장 톤" 과 "오늘 발표된 일정의 의미" 가 **일관됨**
- 매크로 스냅샷 갱신은 macro 도메인의 일 1회 잡으로, 분석 시점에는 캐시된 값을 즉시 사용 → 분석 응답 시간 단축

---

## 5. 운영 메모

| 항목 | 값 |
|------|----|
| Macro 갱신 주기 | 매일 01:00 KST (APScheduler) |
| Macro 캐시 TTL | Redis 25h + 메모리 무제한 (프로세스 단위) |
| Notification 트리거 | LLM 분석 저장 직후 |
| SSE 워커 호환성 | 단일 워커 전제 — 멀티 워커는 외부 브로커 필요 |
| 분석 매크로 지표 수 | 13종 (FRED 1순위 + Yahoo 폴백) |
