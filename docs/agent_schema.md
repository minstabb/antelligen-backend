# Multi-Agent API Schema Document

이 문서는 멀티 에이전트 시스템에서 사용하는 API 스키마를 정의한다.

---

## 1. 전체 구조

```
사용자 → Frontend → Main Agent API → Main Agent
                                        ├── Stock Agent (종목 조회)
                                        ├── News Agent (뉴스 조회)
                                        ├── Finance Agent (재무 조회)
                                        └── Disclosure Agent (공시 조회)
                                              ↓
                                        Frontend Response ← Main Agent 응답 조합
```

---

## 2. Main Agent Input Schema

사용자가 메인 에이전트에게 질문을 전달할 때 사용하는 입력 스키마.

### 스키마 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `query` | string | Y | 사용자 질문 |
| `ticker` | string | N | 종목 코드 |
| `session_id` | string | N | 세션 식별자 (대화 연속성 유지) |
| `user_profile` | object | N | 사용자 투자 성향 |
| `user_profile.risk_level` | string (enum) | Y | 위험 성향 (`conservative`, `balanced`, `aggressive`) |
| `user_profile.investment_horizon` | string (enum) | Y | 투자 기간 (`short`, `mid`, `long`) |
| `options` | object | N | 요청 옵션 |
| `options.agents` | string[] | N | 사용할 에이전트 목록 (미지정 시 자동 선택) |
| `options.max_tokens` | integer | N | 응답 최대 토큰 수 (기본값: 1024) |

### user_profile 값 정의

| 필드 | 값 | 의미 |
|------|-----|------|
| `risk_level` | `conservative` | 안정 추구형 |
| `risk_level` | `balanced` | 균형 투자형 |
| `risk_level` | `aggressive` | 적극 투자형 |
| `investment_horizon` | `short` | 단기 (6개월 이내) |
| `investment_horizon` | `mid` | 중기 (6개월~2년) |
| `investment_horizon` | `long` | 장기 (2년 이상) |

### JSON 예시

```json
{
  "query": "삼성전자 최근 실적과 주가 흐름을 분석해줘",
  "ticker": "005930",
  "session_id": "sess_abc123",
  "user_profile": {
    "risk_level": "balanced",
    "investment_horizon": "mid"
  },
  "options": {
    "agents": ["stock", "finance"],
    "max_tokens": 2048
  }
}
```

### 최소 요청 예시

```json
{
  "query": "SK하이닉스 공시 알려줘"
}
```

### user_profile 포함 최소 예시

```json
{
  "query": "삼성전자 투자 의견 알려줘",
  "ticker": "005930",
  "user_profile": {
    "risk_level": "conservative",
    "investment_horizon": "long"
  }
}
```

---

## 3. Sub Agent Response Schema

각 서브 에이전트가 메인 에이전트에게 반환하는 개별 응답 스키마.

Pydantic 모델: `app.domains.agent.application.response.sub_agent_response.SubAgentResponse`

### 스키마 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `agent_name` | string | Y | 에이전트 이름 (`stock`, `news`, `finance`, `disclosure`) |
| `status` | string (enum) | Y | 처리 상태 (`success`, `error`, `no_data`) |
| `data` | object | N | 에이전트별 응답 데이터 (성공 시 포함) |
| `error_message` | string | N | 에러 발생 시 메시지 |
| `execution_time_ms` | integer | Y | 처리 소요 시간 (밀리초, 0 이상) |
| `signal` | string (enum) | N | 투자 시그널 (`bullish`, `bearish`, `neutral`) — news, finance, disclosure만 포함 |
| `confidence` | float | N | 신뢰도 (0.0 ~ 1.0) — signal 포함 시 함께 제공 |
| `summary` | string | N | 분석 요약 — 메인 에이전트 종합 답변 생성에 사용 |
| `key_points` | string[] | N | 핵심 포인트 — 메인 에이전트 종합 답변 생성에 사용 |

### 상태 값 정의

| status | 의미 | data | error_message |
|--------|------|------|---------------|
| `success` | 정상 처리 완료 | 응답 데이터 포함 | null |
| `error` | 처리 중 오류 발생 | null | 에러 메시지 포함 |
| `no_data` | 정상 처리했으나 결과 없음 | null | null |

### JSON 예시 - Stock Agent 성공 응답

stock 에이전트는 시그널 분석을 수행하지 않으므로 signal 관련 필드는 null이다.

```json
{
  "agent_name": "stock",
  "status": "success",
  "data": {
    "ticker": "005930",
    "stock_name": "삼성전자",
    "market": "KOSPI",
    "current_price": 72000,
    "change_rate": -1.23
  },
  "error_message": null,
  "execution_time_ms": 245,
  "signal": null,
  "confidence": null,
  "summary": null,
  "key_points": null
}
```

### JSON 예시 - News Agent 성공 응답

```json
{
  "agent_name": "news",
  "status": "success",
  "data": {
    "ticker": "005930",
    "articles": [
      {
        "title": "삼성전자, AI 반도체 투자 확대",
        "source": "한국경제",
        "published_at": "2026-03-15T09:00:00Z",
        "url": "https://example.com/article/1"
      }
    ]
  },
  "error_message": null,
  "execution_time_ms": 380,
  "signal": "bullish",
  "confidence": 0.82,
  "summary": "삼성전자 AI 반도체 투자 확대 발표로 긍정적 전망",
  "key_points": [
    "AI 반도체 설비 투자 3조원 추가 확정",
    "HBM4 양산 일정 앞당김",
    "주요 외국계 증권사 목표가 상향"
  ]
}
```

### JSON 예시 - Finance Agent 성공 응답

```json
{
  "agent_name": "finance",
  "status": "success",
  "data": {
    "ticker": "005930",
    "revenue": "258조 1600억",
    "operating_profit": "6조 5400억",
    "net_income": "15조 8200억",
    "period": "2025-Q4"
  },
  "error_message": null,
  "execution_time_ms": 512,
  "signal": "neutral",
  "confidence": 0.55,
  "summary": "매출 성장세 유지되나 영업이익률 소폭 하락",
  "key_points": [
    "2025-Q4 매출 258조 1600억 (전년 대비 +12%)",
    "영업이익률 2.5%로 전분기 대비 하락",
    "반도체 부문 회복세 지속"
  ]
}
```

### JSON 예시 - Disclosure Agent 성공 응답

```json
{
  "agent_name": "disclosure",
  "status": "success",
  "data": {
    "ticker": "005930",
    "filings": [
      {
        "title": "사업보고서 (2025.12)",
        "filed_at": "2026-03-14",
        "type": "annual_report"
      }
    ]
  },
  "error_message": null,
  "execution_time_ms": 290,
  "signal": "bearish",
  "confidence": 0.71,
  "summary": "자기주식 처분 공시로 단기 수급 부담",
  "key_points": [
    "자기주식 500만주 처분 결정",
    "처분 예정 기간 3개월",
    "단기 주가 희석 우려"
  ]
}
```

### JSON 예시 - 에러 응답

```json
{
  "agent_name": "news",
  "status": "error",
  "data": null,
  "error_message": "외부 뉴스 API 연결 시간 초과",
  "execution_time_ms": 5000,
  "signal": null,
  "confidence": null,
  "summary": null,
  "key_points": null
}
```

### JSON 예시 - 데이터 없음 응답

```json
{
  "agent_name": "disclosure",
  "status": "no_data",
  "data": null,
  "error_message": null,
  "execution_time_ms": 150,
  "signal": null,
  "confidence": null,
  "summary": null,
  "key_points": null
}
```

---

## 3-1. Investment Signal Response Schema

서브 에이전트(news, finance, disclosure)가 투자 시그널 분석 결과를 생성할 때 사용하는 **내부 중간 모델**이다.

이 모델의 필드(`signal`, `confidence`, `summary`, `key_points`)는 `SubAgentResponse`를 조립할 때 최상위 필드로 매핑된다.

Pydantic 모델: `app.domains.agent.application.response.investment_signal_response.InvestmentSignalResponse`

### 스키마 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `agent_name` | string | Y | 에이전트 이름 (`news`, `finance`, `disclosure`) |
| `ticker` | string | Y | 종목 코드 |
| `signal` | string (enum) | Y | 투자 시그널 (`bullish`, `bearish`, `neutral`) |
| `confidence` | float | Y | 신뢰도 (0.0 ~ 1.0) |
| `summary` | string | Y | 분석 요약 |
| `key_points` | string[] | Y | 핵심 포인트 (최소 1개) |

### signal 값 정의

| signal | 의미 |
|--------|------|
| `bullish` | 매수 시그널 (긍정적 전망) |
| `bearish` | 매도 시그널 (부정적 전망) |
| `neutral` | 중립 (관망) |

### JSON 예시 - News Agent 투자 시그널

```json
{
  "agent_name": "news",
  "ticker": "005930",
  "signal": "bullish",
  "confidence": 0.82,
  "summary": "삼성전자 AI 반도체 투자 확대 발표로 긍정적 전망",
  "key_points": [
    "AI 반도체 설비 투자 3조원 추가 확정",
    "HBM4 양산 일정 앞당김",
    "주요 외국계 증권사 목표가 상향"
  ]
}
```

### JSON 예시 - Finance Agent 투자 시그널

```json
{
  "agent_name": "finance",
  "ticker": "005930",
  "signal": "neutral",
  "confidence": 0.55,
  "summary": "매출 성장세 유지되나 영업이익률 소폭 하락",
  "key_points": [
    "2025-Q4 매출 258조 1600억 (전년 대비 +12%)",
    "영업이익률 2.5%로 전분기 대비 하락",
    "반도체 부문 회복세 지속"
  ]
}
```

### JSON 예시 - Disclosure Agent 투자 시그널

```json
{
  "agent_name": "disclosure",
  "ticker": "005930",
  "signal": "bearish",
  "confidence": 0.71,
  "summary": "자기주식 처분 공시로 단기 수급 부담",
  "key_points": [
    "자기주식 500만주 처분 결정",
    "처분 예정 기간 3개월",
    "단기 주가 희석 우려"
  ]
}
```

---

## 4. Frontend Response Schema

메인 에이전트가 모든 서브 에이전트 응답을 조합하여 프론트엔드에 반환하는 최종 응답 스키마.

공통 래퍼: `app.common.response.base_response.BaseResponse`
프론트엔드 DTO: `app.domains.agent.application.response.frontend_agent_response.FrontendAgentResponse`
내부 응답 모델: `app.domains.agent.application.response.agent_query_response.AgentQueryResponse`

프론트엔드 전용 DTO는 내부 응답의 비즈니스 로직(상태 판정 등)을 포함하지 않으며,
`FrontendAgentResponse.from_internal()`을 통해 내부 응답에서 변환된다.

### 스키마 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `success` | boolean | Y | 요청 성공 여부 |
| `message` | string | Y | 응답 메시지 |
| `data` | object | N | 응답 데이터 (실패 시 null) |
| `data.session_id` | string | Y | 세션 식별자 |
| `data.result_status` | string (enum) | Y | 종합 결과 상태 (`success`, `partial_failure`, `failure`) |
| `data.answer` | string | Y | 메인 에이전트가 생성한 종합 답변 |
| `data.agent_results` | SubAgentResponse[] | Y | 각 서브 에이전트 응답 목록 |
| `data.total_execution_time_ms` | integer | Y | 전체 처리 소요 시간 (밀리초) |

### result_status 판정 규칙

| result_status | 조건 |
|---------------|------|
| `success` | 모든 서브 에이전트가 success |
| `partial_failure` | 일부 서브 에이전트가 success, 일부가 error 또는 no_data |
| `failure` | 모든 서브 에이전트가 error 또는 no_data, 또는 결과 없음 |

### JSON 예시 - 성공 응답 (result_status: success)

```json
{
  "success": true,
  "message": "success",
  "data": {
    "session_id": "sess_abc123",
    "result_status": "success",
    "answer": "삼성전자(005930)는 현재 72,000원으로 전일 대비 1.23% 하락했습니다. 2025년 4분기 매출은 258조 1600억원, 영업이익은 6조 5400억원을 기록했습니다.",
    "agent_results": [
      {
        "agent_name": "stock",
        "status": "success",
        "data": {
          "ticker": "005930",
          "stock_name": "삼성전자",
          "market": "KOSPI",
          "current_price": 72000,
          "change_rate": -1.23
        },
        "error_message": null,
        "execution_time_ms": 245
      },
      {
        "agent_name": "finance",
        "status": "success",
        "data": {
          "ticker": "005930",
          "revenue": "258조 1600억",
          "operating_profit": "6조 5400억",
          "net_income": "15조 8200억",
          "period": "2025-Q4"
        },
        "error_message": null,
        "execution_time_ms": 512
      }
    ],
    "total_execution_time_ms": 1823
  }
}
```

### JSON 예시 - 부분 실패 응답 (result_status: partial_failure)

```json
{
  "success": true,
  "message": "success",
  "data": {
    "session_id": "sess_abc123",
    "result_status": "partial_failure",
    "answer": "SK하이닉스 종목 정보를 조회했습니다. 다만 뉴스 조회에 실패하여 뉴스 정보는 포함되지 않았습니다.",
    "agent_results": [
      {
        "agent_name": "stock",
        "status": "success",
        "data": {
          "ticker": "000660",
          "stock_name": "SK하이닉스",
          "market": "KOSPI"
        },
        "error_message": null,
        "execution_time_ms": 230
      },
      {
        "agent_name": "news",
        "status": "error",
        "data": null,
        "error_message": "외부 뉴스 API 연결 시간 초과",
        "execution_time_ms": 5000
      }
    ],
    "total_execution_time_ms": 5312
  }
}
```

### JSON 예시 - 전체 실패 응답 (result_status: failure)

```json
{
  "success": true,
  "message": "success",
  "data": {
    "session_id": "sess_abc123",
    "result_status": "failure",
    "answer": "요청하신 정보를 조회할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    "agent_results": [
      {
        "agent_name": "stock",
        "status": "error",
        "data": null,
        "error_message": "데이터베이스 연결 실패",
        "execution_time_ms": 3000
      },
      {
        "agent_name": "finance",
        "status": "error",
        "data": null,
        "error_message": "외부 API 응답 시간 초과",
        "execution_time_ms": 5000
      }
    ],
    "total_execution_time_ms": 5100
  }
}
```

### JSON 예시 - 요청 자체 실패 응답

```json
{
  "success": false,
  "message": "질문을 처리할 수 없습니다.",
  "data": null
}
```

---

## 5. API Endpoint 요약

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/agent/query` | 메인 에이전트 질문 요청 |
| GET | `/api/v1/agent-schema` | 멀티 에이전트 API 스키마 자동 생성 |
| POST | `/api/v1/post` | 게시물 생성 |
| GET | `/api/v1/stock/{ticker}` | 종목 조회 |

---

## 6. 스키마 버전

| 항목 | 값 |
|------|-----|
| 스키마 버전 | 1.0.0 |
| 최종 수정일 | 2026-03-16 |
