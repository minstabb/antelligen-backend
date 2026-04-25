# ADR-0001: `period` 파라미터를 **candle interval** 로 재해석

## Status

Accepted — 2026-04-22

## Context

대시보드 히스토리 패널/차트의 UI 탭 레이블 `1D / 1W / 1M / 1Y` 는 설계상 **캔들 봉 단위**
(candle interval) 를 의미했다. 즉:

- `1D` → 일봉 (daily candle, 1봉 = 1거래일)
- `1W` → 주봉 (weekly, 1봉 = 1주)
- `1M` → 월봉 (monthly, 1봉 = 1달)
- `1Y` → 연봉 (yearly, 1봉 = 1년)

그러나 실제 구현은 두 가지 결함이 결합되어 탭 전환이 **봉 단위 변경**으로 이어지지 않았다.

### 결함 1 — yfinance `interval` 하드코딩

`app/domains/dashboard/adapter/outbound/external/yahoo_finance_stock_client.py` 에서:

```python
df = t.history(period=period, interval="1d")  # ← "1d" 하드코딩
```

위 코드로 인해 어떤 탭을 눌러도 **항상 일봉 데이터**가 내려왔다. 1Y 탭도 20년치 일봉 데이터를
받아 화면에 압축 렌더했을 뿐, 연봉 20개가 아니었다.

### 결함 2 — `_PERIOD_TO_DAYS` 값이 lookback을 의미

소스마다 `period` 문자열을 다른 일수로 매핑해 **UI 직관과 어긋남**.

| 소스 | 1D | 1W | 1M | 1Y |
|---|---|---|---|---|
| PRICE | 365일 | 1,095일 | 1,825일 | **7,300일 (20Y)** |
| NEWS | 90일(fallback) | 7일 | 30일 | 365일 |
| MACRO | — | 7일 | 30일 | 365일 |

1Y 탭에서 PRICE 이벤트가 수천 건(NVDA 1Y 1,225건) 쏟아져 임시 cap (`history_price_event_cap=80`)을
도입해야 했다. `period` 의미가 명확하지 않아 오독·반복 논의·잘못된 리팩터링 시도가 누적됨.

### 결함 3 — 네이밍이 다의적

`period` 는 영어에서 "기간", "주기" 양쪽 의미로 쓰이는 단어. Python·JS 두 코드베이스 + yfinance
자체의 `period` / `interval` 구분과 충돌해 AI/새 개발자가 첫 탐색 시 **거의 확정적으로 오독**.

2026-04 세션에서 Claude 가 `period = lookback duration` 으로 **두 번 연속 오독**, 잘못된 방향의
재설계 계획(§12) 전체를 작성했다가 사용자가 "1D/1W/1M/1Y 는 봉 단위 맞지?" 라고 확인하며 원
설계 의도가 복원됨.

## Decision

1. **의미 분리 — 명시적 네이밍**
   - 봉 단위 (candle interval) → `chart_interval` (Python) / `chartInterval` (TS)
     - 값 집합: `"1D" | "1W" | "1M" | "1Q"`
     - `"1Y"` 는 **deprecated 별칭** — 내부에서 `"1Q"` 로 매핑
   - 조회 기간 (lookback duration) → `lookback_range` / `lookbackRange`
     - 값 집합: `"1M" | "3M" | "6M" | "1Y" | "5Y" | "10Y"`
     - macro-timeline 같이 봉 단위와 무관한 시간 범위 지칭 시 사용
   - `period` 라는 이름은 **신규 코드에서 사용 금지**. 기존 API 는 backward compat 별칭으로 유지.

2. **yfinance 매핑 매트릭스 고정**

   `chart_interval` → (yfinance `period`, yfinance `interval`):

   | chart_interval | yfinance.period | yfinance.interval | 의미 |
   |---|---|---|---|
   | `1D` | `1y`  | `1d`  | 일봉 × 252봉 |
   | `1W` | `3y`  | `1wk` | 주봉 × 156봉 |
   | `1M` | `5y`  | `1mo` | 월봉 × 60봉 |
   | `1Q` | `max` | `3mo` | 분기봉 × ~80봉 (20년) |

   연봉은 yfinance 미지원이므로 `3mo` (분기봉) 로 대체 + UI 레이블을 `"분기"` 로 표시.

3. **API 파라미터 이름 전환**
   - `GET /history-agent/timeline?chart_interval=1M` (신규 권장)
   - `GET /history-agent/timeline?period=1M` (deprecated, 하위 호환 유지)
   - `GET /history-agent/macro-timeline?lookback=5Y` (추후 macro 쪽도 rename 예정)

4. **이상치 봉 마커 신규 엔드포인트**
   - `GET /history-agent/anomaly-bars?ticker=X&chart_interval=P`
   - PRICE 카테고리를 히스토리에서 제거하고 차트 ★ 마커 + causality popover 로 이동.
   - 봉 단위별 adaptive threshold (k=2.5 × σ + floor) 로 평상시 대비 특이한 봉만 선별.

## Consequences

### 긍정

- 탭 전환이 **실제로 봉 단위 전환**으로 작동 — 설계 원의도 복원.
- `period` 의 다의성 제거로 AI/새 개발자 오독 빈도 ↓.
- PRICE 카테고리 제거로 UI 단순화, `history_price_event_cap` 같은 임시방편 철거.
- 이상치 봉 마커가 차트-중심 UX 에 자연스럽게 부합.

### 부정 / 주의

- 프론트·백엔드 동시 배포 필요 (또는 별칭 유지 기간 관리).
- `1Y` 탭 (분기봉) 은 UI 레이블 `"분기"` 로 변경되어 기존 사용자 혼란 가능성 — CTA·툴팁으로
  완화.
- yfinance `period="max"` 호출 시 응답 크기가 커짐 (분기봉 ~80봉은 충분히 작지만 최초 네트워크
  비용 주의).
- Redis 캐시 키 `v3 → v4` 전환 시 cold miss 1회 발생 (단기 영향).

## Alternatives Considered

### §12 "period = lookback duration" 방향 (DEPRECATED)

2026-04 세션 초반, 현재 구현이 여러 탭에서 일봉 동일 데이터를 반환하는 것을 관찰하고
`period = lookback duration` 이라는 **잘못된 전제** 위에서 "period 서버 파라미터 제거" (§12.3 🅴)
및 "significance 태깅" (§12.3 🅴-2) 방향을 검토했으나 원 설계 의도와 어긋나 폐기.

### 서버 측 연봉 집계

`interval="3mo"` 대신 일봉을 받아 서버에서 연도별 집계하는 방안(plan §17 옵션 B). 정확도는 더
높으나 네트워크·CPU 비용 증가. 현재는 분기봉이 "장기 추세" 용도로 충분하다는 판단으로 제외.

### Beta 기반 동적 k 조정

이상치 판정의 `k` 값을 종목별 β(시장 대비 민감도)로 동적 조정. 정밀도는 ↑ 이나 β 측정·업데이트
infra 필요. Future follow-up 으로 유보.

## 관련

- Plan: `~/.claude/plans/antelligen-composed-quail.md` §13 / §17
- Memory: `~/.claude/projects/.../memory/project_antelligen_period_redesign.md`
- Memory: `~/.claude/projects/.../memory/feedback_period_naming.md`
- Quality report: `tests/quality/history_timeline_report.md` §5 (Top 10) / §15 / §16
