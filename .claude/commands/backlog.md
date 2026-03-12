# Command: /backlog

## 목적

사용자가 Backlog Title을 입력하면  
Behavior Backlog를 생성한다.

이 Command는  
`.claude/skills/BEHAVIOR_BACKLOG_GENERATOR.md` 규칙을 사용한다.

---

## 사용 방법

```
/backlog <Backlog Title>
```

예시

```
/backlog 인증되지 않은 사용자가 게시물 리스트를 조회한다
```

또는

```
/backlog 애플리케이션이 .env 환경 변수를 로드한다
```

---

## 동작 규칙

1. 사용자가 입력한 Backlog Title을 읽는다
2. `.claude/skills/BEHAVIOR_BACKLOG_GENERATOR.md`의 규칙을 적용한다
3. 다음 구조의 Agile Backlog를 생성한다

출력 구조

Backlog Title  
Success Criteria  
Todo

---

## 출력 형식

Backlog Title  
<입력된 제목>

Success Criteria

- ...
- ...
- ...

Todo

1. ...
2. ...
3. ...
4. ...
5. ...

Todo는 **최대 5개까지만 작성한다.**

---

## Title 검증 규칙

Title은 반드시 다음 구조여야 한다.

Actor + 행동 + 대상

Actor는 다음 중 하나여야 한다.

### User Actor

권한 상태 또는 역할이 포함된 사용자

예

- 인증된 사용자
- 인증되지 않은 사용자
- 관리자
- 시스템 관리자
- 게스트 사용자

### System Actor

시스템 동작을 표현하는 구성 요소

예

- 애플리케이션
- 시스템
- 백엔드 서버
- API 서버

---

## Title 예시

User Behavior

인증된 사용자가 게시물을 생성한다  
인증되지 않은 사용자가 게시물 리스트를 조회한다  
관리자가 게시물을 삭제한다  

System Behavior

애플리케이션이 .env 환경 변수를 로드한다  
시스템이 Redis 캐시를 초기화한다  
백엔드 서버가 로그 파일을 기록한다  

---

## 규칙 위반 처리

Title이 규칙을 만족하지 않으면  
Backlog를 생성하지 않고 다음 가이드를 출력한다.

Backlog Title이 규칙을 만족하지 않습니다.

Backlog Title은 다음 형식을 따라야 합니다.

Actor + 행동 + 대상

Actor는 다음 중 하나여야 합니다.

User Actor 예

- 인증된 사용자
- 인증되지 않은 사용자
- 관리자

System Actor 예

- 애플리케이션
- 시스템
- 백엔드 서버
- API 서버

예시

인증된 사용자가 게시물을 생성한다  
인증되지 않은 사용자가 게시물 리스트를 조회한다  
애플리케이션이 .env 환경 변수를 로드한다