# CLAUDE.md

## Project Overview

Antelligen Backend — FastAPI + Hexagonal Architecture + DDD (Python)

## Commands

- **Run dev server**: `uvicorn main:app --reload --host 0.0.0.0 --port 33333`
- **Run directly**: `python main.py` (port 33333)
- Async route handlers (`async def`)

## Git 워크플로우

main에 직접 푸시 금지. 항상 PR 워크플로우 사용.

1. `passgiant` fork에 작업 브랜치 생성 후 푸시
2. `passgiant/branch` → `EDDI-RobotAcademy/main` PR 생성
3. **merge commit**으로 머지 (squash 금지 — 원본 커밋 SHA 보존)
4. 머지 후 반드시 fork sync 실행:
   ```bash
   git fetch upstream && git merge --ff-only upstream/main && git push origin main
   ```

- origin: `passgiant/antelligen-*` (fork)
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

