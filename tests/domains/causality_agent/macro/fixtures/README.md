# INDEX Macro Causality Golden Set

T2-1 Phase B LLM 매크로 causality의 품질 평가용 고정 샘플 30건.

## 포맷

각 샘플은 `sample_{nn}.json` 파일:

```json
{
  "index_ticker": "^IXIC",
  "event": {
    "date": "2024-09-18",
    "type": "SURGE",
    "change_pct": 2.1,
    "title": "연준 금리 인하"
  },
  "context_macro": [
    {
      "date": "2024-09-18",
      "type": "INTEREST_RATE",
      "change_pct": -0.5,
      "title": "기준금리 50bp 인하"
    }
  ],
  "expected_keywords": ["금리", "인하", "완화"],
  "unacceptable_keywords": ["실업률", "유가"]
}
```

## 평가 기준 (Phase B 런칭 전 통과 필수)

1. **정확성:** 생성된 hypothesis에 `expected_keywords` 중 ≥1개 포함 (30건 중 ≥21건 통과 = 70%).
2. **금칙:** `unacceptable_keywords`는 0건 포함.
3. **형식:** JSON 배열 + 각 항목 "원인 → 결과" 형식.
4. **비용:** 샘플당 평균 토큰 < 8k.
5. **지연:** 샘플당 평균 지연 < 5s.

평가 실행:
```bash
pytest tests/domains/causality_agent/macro/test_golden_set.py --eval
```

기준 미통과 시 `settings.index_causality_llm_enabled`는 계속 `False`로 유지해야 한다.
