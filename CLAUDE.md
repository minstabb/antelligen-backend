# CLAUDE.md

## Project Overview

Antelligen Backend — FastAPI + Hexagonal Architecture + DDD (Python)

## Commands

- **Run dev server**: `uvicorn main:app --reload --host 0.0.0.0 --port 33333`
- **Run directly**: `python main.py` (port 33333)
- Async route handlers (`async def`)

## Git 워크플로우

main에 직접 푸시 금지. 항상 PR 워크플로우 사용.

1. fork (예: `K-MG-0328/antelligen-backend`)에 작업 브랜치 생성 후 푸시
2. `origin/branch` → `EDDI-RobotAcademy/main` PR 생성
3. **merge commit**으로 머지 (squash 금지 — 원본 커밋 SHA 보존)
4. 머지 후 반드시 fork sync 실행:
   ```bash
   git fetch upstream && git merge --ff-only upstream/main && git push origin main
   ```

- origin: 사용자 fork (예: `K-MG-0328/antelligen-*`)
- upstream: `EDDI-RobotAcademy/antelligen-*` (원본)

## 프로젝트 구조

```
app
 ├ domains/<domain>/
 │   ├ domain/           entity, value_object, service
 │   ├ application/      usecase, request, response
 │   ├ adapter/
 │   │   ├ inbound/api
 │   │   └ outbound/     persistence, external
 │   └ infrastructure/   orm, mapper
 ├ infrastructure/        config, database, cache, external
 └ main.py
```

## 레이어 의존성

```
Adapter → Application → Domain
Infrastructure → Adapter / Application
```

## 레이어별 MUST 규칙

### Domain — 순수 Python만 허용

import 절대 금지: `FastAPI` `SQLAlchemy` `Redis` `Pydantic` `HTTP Client` `External API` `ORM Model` `env 설정`

### Application — UseCase 레이어

직접 사용 금지: `FastAPI` `SQLAlchemy ORM` `Redis` `External API Client`
외부 시스템은 반드시 Port/Adapter를 통해서만 접근

### Adapter

- **Inbound** (`adapter/inbound/api`): FastAPI Router만 위치. 비즈니스 로직 작성 금지. Request → UseCase → Response 흐름만 담당
- **Outbound** (`adapter/outbound`): Repository 구현, External API Client, Cache Adapter

### Infrastructure (`infrastructure/`)

DB Session, ORM Model, Redis Client, env 설정, External API 공통 Client 위치

## ORM / Mapper / DTO 규칙

- ORM Model: `domains/<domain>/infrastructure/orm` — Domain Entity와 반드시 분리
- Mapper: `domains/<domain>/infrastructure/mapper` — ORM ↔ Domain Entity 변환 담당
- DTO: `application/request`, `application/response` — Domain Entity를 API Response로 직접 반환 금지
- Domain Entity는 SQLAlchemy Model import 금지

## DI 흐름

```
Router → UseCase → Repository → Infrastructure
```

의존성 연결은 `main.py` 또는 DI 모듈에서 수행

## 금지 코드

```python
from sqlalchemy import Column    # Domain에서 ORM 사용
from fastapi import APIRouter    # Domain에서 FastAPI 사용
redis.Redis(...)                 # UseCase에서 Redis 직접 생성
```

## 네이밍 규칙

### 시간 관련 파라미터 (ADR-0001 참조)

- **봉 단위 (candle interval)** → `chart_interval` (Python) / `chartInterval` (TS)
  - 값: `"1D" | "1W" | "1M" | "1Q"`
  - 예: `GET /history-agent/timeline?chart_interval=1M`
- **조회 기간 (lookback duration)** → `lookback_range` / `lookbackRange`
  - 값: `"1M" | "3M" | "6M" | "1Y" | "5Y" | "10Y"`
  - 예: `GET /history-agent/macro-timeline?lookback=5Y` (추후 rename 예정)
- **`period` 는 신규 코드에서 사용 금지** — 기존 API 는 deprecation 별칭으로 유지.
- **`1Y` chart_interval 값은 deprecated** — 내부에서 `1Q` 로 자동 매핑 (yfinance 연봉 미지원).

상세 설계 배경: `docs/adr/0001-period-as-candle-interval.md`

