# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pioneer Team Backend — a Python FastAPI application.

## Commands

- **Run dev server**: `uvicorn main:app --reload --host 0.0.0.0 --port 33333`
- **Run directly**: `python main.py` (starts on port 33333)

## Architecture

- `main.py` — FastAPI application entry point
- `test_main.http` — HTTP request file for manual endpoint testing (JetBrains HTTP client format)

## Git 워크플로우

코드 변경 시 main에 직접 푸시하지 말고 항상 PR 워크플로우를 사용한다.

1. `passgiant` fork에 작업 브랜치 생성
2. 코드 변경 + 브랜치에 푸시
3. `passgiant/branch` → `EDDI-RobotAcademy/main` 으로 PR 생성
4. PR 승인 (APPROVE)
5. 머지

- origin: `passgiant/antelligen-*` (fork)
- upstream: `EDDI-RobotAcademy/antelligen-*` (원본)

## Conventions

- Async route handlers (`async def`)
- Server runs on port 33333

## 목적

이 프로젝트는 **FastAPI 기반 Hexagonal Architecture + Domain Driven Design (DDD)** 구조를 따른다.

이 문서의 목적은 다음과 같다.

- AI가 코드를 생성할 때 아키텍처 규칙을 위반하지 않도록 강제
- Domain, Application, Adapter, Infrastructure 레이어의 명확한 역할 분리
- ORM, Redis, External API, Environment 설정 등의 올바른 위치 규정
- 유지보수성과 확장성을 고려한 일관된 코드 구조 유지

이 문서에 정의된 규칙은 항상 준수되어야 한다.

---

# 프로젝트 구조

프로젝트는 다음과 같은 디렉토리 구조를 따른다.

```
app
 ├ domains
 │   └ <domain_name>
 │       ├ domain
 │       │   ├ entity
 │       │   ├ value_object
 │       │   └ service
 │       │
 │       ├ application
 │       │   ├ usecase
 │       │   ├ request
 │       │   └ response
 │       │
 │       ├ adapter
 │       │   ├ inbound
 │       │   │   └ api
 │       │   │
 │       │   └ outbound
 │       │       ├ persistence
 │       │       └ external
 │       │
 │       └ infrastructure
 │           ├ orm
 │           └ mapper
 │
 ├ infrastructure
 │   ├ config
 │   ├ database
 │   ├ cache
 │   └ external
 │
 └ main.py
```

---

# 아키텍처 원칙

이 프로젝트는 **Hexagonal Architecture (Ports and Adapters)** 를 따른다.

레이어 의존성 방향은 다음과 같다.

```
Adapter → Application → Domain
Infrastructure → Adapter / Application
```

의존성은 항상 **안쪽 레이어 방향으로만 흐른다.**

---

# Domain Layer 규칙

Domain 레이어는 **비즈니스 로직의 핵심**이다.

Domain에는 다음만 포함될 수 있다.

- Entity
- Value Object
- Domain Service
- Domain Business Rule

## Domain Layer MUST 규칙

Domain 레이어는 다음을 **절대 import하면 안 된다.**

- FastAPI
- SQLAlchemy
- Redis
- Pydantic
- HTTP Client
- External API
- Environment 설정
- ORM Model

Domain 코드는 **순수 Python 코드**여야 한다.

---

# Application Layer 규칙

Application 레이어는 **UseCase를 정의하는 레이어**이다.

Application 레이어의 역할

- UseCase 실행
- Domain Entity 조합
- Repository Port 호출
- Request / Response DTO 정의

## Application Layer MUST 규칙

Application 레이어는 다음을 **직접 사용하면 안 된다.**

- FastAPI
- SQLAlchemy ORM
- Redis
- External API Client

외부 시스템 접근은 **Port 또는 Adapter를 통해서만 접근해야 한다.**

---

# Request / Response DTO 규칙

API 입력과 출력은 **Domain Entity와 반드시 분리해야 한다.**

Request / Response DTO는 **Application Layer에 위치해야 한다.**

```
application
 ├ request
 └ response
```

## MUST 규칙

Domain Entity를 **API Response로 직접 반환하면 안 된다.**

항상 DTO를 사용해야 한다.

---

# Adapter Layer 규칙

Adapter 레이어는 **외부 인터페이스와 Application 사이를 연결하는 역할**을 한다.

Adapter는 두 가지로 나뉜다.

## Inbound Adapter

외부 요청을 Application으로 전달한다.

예시

- FastAPI Router
- REST API Endpoint

위치

```
adapter/inbound/api
```

---

## Outbound Adapter

Application이 외부 시스템을 사용할 수 있도록 구현한다.

예시

- Repository 구현
- External API Client
- Cache Adapter

위치

```
adapter/outbound
```

---

# Infrastructure Layer 규칙

Infrastructure 레이어는 **기술적인 구현 요소**를 포함한다.

포함되는 요소

- Database Session
- ORM Model
- Redis Client
- Environment 설정
- External API 공통 Client
- Logging 설정

위치

```
infrastructure
```

예시

```
infrastructure
 ├ config
 ├ database
 ├ cache
 └ external
```

---

# ORM 규칙

ORM Model은 **Domain Entity와 반드시 분리해야 한다.**

ORM Model 위치

```
domains/<domain>/infrastructure/orm
```

## MUST 규칙

Domain Entity는 **SQLAlchemy Model을 import하면 안 된다.**

---

# Mapper 규칙

ORM Model과 Domain Entity 사이에는 **Mapper가 필요하다.**

위치

```
domains/<domain>/infrastructure/mapper
```

Mapper 역할

```
ORM Model → Domain Entity
Domain Entity → ORM Model
```

---

# Redis 규칙

Redis Client는 **Infrastructure Layer에 위치해야 한다.**

위치

```
infrastructure/cache
```

Application 또는 Adapter는 Redis를 사용할 수 있지만  
**Domain 레이어는 Redis를 알면 안 된다.**

---

# Environment 설정 규칙

환경 변수는 **Pydantic BaseSettings 기반으로 관리한다.**

위치

```
infrastructure/config
```

예시 파일

```
settings.py
```

## MUST 규칙

Environment 변수는 **Domain Layer에서 사용하면 안 된다.**

---

# External API Client 규칙

외부 API Client는 **Outbound Adapter 또는 Infrastructure에 위치한다.**

예시

- OpenAI
- Slack
- Github
- Payment API

Domain 레이어는 External API를 알면 안 된다.

---

# FastAPI Router 규칙

FastAPI Router는 **Inbound Adapter에 위치해야 한다.**

위치

```
adapter/inbound/api
```

Router의 역할

- Request DTO 수신
- UseCase 호출
- Response DTO 반환

## MUST 규칙

Router에서 **비즈니스 로직을 작성하면 안 된다.**

---

# Dependency Injection 규칙

의존성 흐름

```
Router → UseCase → Repository → Infrastructure
```

의존성 연결은 **main.py 또는 DI 모듈에서 수행한다.**

---

# 금지 사항

다음 코드는 **절대 작성하면 안 된다.**

### Domain에서 ORM 사용

```
from sqlalchemy import Column
```

### Domain에서 FastAPI 사용

```
from fastapi import APIRouter
```

### UseCase에서 Redis 직접 생성

```
redis.Redis(...)
```

---

# 최종 원칙

다음 규칙은 **항상 지켜져야 한다.**

- Domain Layer는 순수 Python이어야 한다.
- ORM Model은 Domain Entity와 분리되어야 한다.
- Request / Response DTO는 Domain Entity와 분리되어야 한다.
- Redis / Database / External API는 Infrastructure 또는 Adapter에서만 사용해야 한다.
- Router에는 비즈니스 로직을 작성하면 안 된다.

모든 코드는 **이 CLAUDE.md 규칙을 MUST 준수해야 한다.**