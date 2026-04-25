"""
History Timeline 품질 검증 스모크 스크립트 (read-only).

사용법:
    .venv/bin/python tests/quality/smoke_history_timeline.py

동작:
1. 미리 정의된 티커×period 매트릭스를 cold→warm 2회 호출
2. 응답 JSON을 tests/quality/samples/{slug}.json에 저장
3. 축 C(중복/누락/경계) 자동 체크 결과를 tests/quality/matrix.json에 축적
4. 5xx / 이상치만 stdout에 요약 출력

이미 기동 중인 백엔드(localhost:33333)에 의존. 별도 DB/LLM mocking 없음 (실제 LLM 호출).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
MATRIX_PATH = ROOT / "matrix.json"
BASE = "http://localhost:33333"
TIMEOUT = 180.0

# (endpoint, label, params) 형태로 관리
MATRIX: list[tuple[str, str, dict[str, Any]]] = [
    # EQUITY US
    ("timeline", "AAPL_1M", {"ticker": "AAPL", "period": "1M", "enrich_titles": "false"}),
    ("timeline", "AAPL_1Y", {"ticker": "AAPL", "period": "1Y", "enrich_titles": "false"}),
    ("timeline", "NVDA_1Y", {"ticker": "NVDA", "period": "1Y", "enrich_titles": "false"}),
    # EQUITY KR
    ("timeline", "005930_1M", {"ticker": "005930", "period": "1M", "enrich_titles": "false"}),
    ("timeline", "005930_1Y", {"ticker": "005930", "period": "1Y", "enrich_titles": "false"}),
    # INDEX
    ("timeline", "IXIC_1M", {"ticker": "^IXIC", "period": "1M", "enrich_titles": "false"}),
    ("timeline", "IXIC_1Y", {"ticker": "^IXIC", "period": "1Y", "enrich_titles": "false"}),
    ("timeline", "GSPC_1Y", {"ticker": "^GSPC", "period": "1Y", "enrich_titles": "false"}),
    ("timeline", "KS11_1Y", {"ticker": "^KS11", "period": "1Y", "enrich_titles": "false"}),
    # ETF
    ("timeline", "SPY_1M", {"ticker": "SPY", "period": "1M", "enrich_titles": "false"}),
    ("timeline", "QQQ_1M", {"ticker": "QQQ", "period": "1M", "enrich_titles": "false"}),
    # MACRO-only
    ("macro-timeline", "MACRO_US_1Y", {"region": "US", "period": "1Y"}),
    ("macro-timeline", "MACRO_KR_1Y", {"region": "KR", "period": "1Y"}),
    ("macro-timeline", "MACRO_GLOBAL_5Y", {"region": "GLOBAL", "period": "5Y"}),
    ("macro-timeline", "MACRO_US_10Y", {"region": "US", "period": "10Y"}),
]


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or payload
    events = data.get("events") or []
    cat_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    macro_dup_keys: list[tuple[str, str]] = []
    macro_seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    seen_title_date: set[tuple[str, str]] = set()
    has_high_52w = False
    importance_scores: list[float] = []
    causality_count = 0
    for ev in events:
        cat = ev.get("category", "?")
        typ = ev.get("type", "?")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        type_counts[typ] = type_counts.get(typ, 0) + 1
        if typ == "HIGH_52W":
            has_high_52w = True
        if cat == "MACRO":
            key = (ev.get("date", ""), typ)
            if key in macro_seen:
                macro_dup_keys.append(key)
            macro_seen.add(key)
        sig = (ev.get("date", ""), ev.get("title", ""))
        if sig in seen_title_date:
            duplicates.append(f"{sig[0]}::{sig[1]}")
        seen_title_date.add(sig)
        score = ev.get("importance_score")
        if score is not None:
            importance_scores.append(float(score))
        if ev.get("causality"):
            causality_count += 1
    return {
        "count": data.get("count"),
        "len_events": len(events),
        "is_etf": data.get("is_etf"),
        "asset_type": data.get("asset_type"),
        "region": data.get("region"),
        "category_counts": cat_counts,
        "type_counts_top5": dict(sorted(type_counts.items(), key=lambda x: -x[1])[:5]),
        "has_high_52w": has_high_52w,
        "macro_dup_keys": [list(k) for k in macro_dup_keys],
        "same_date_title_duplicates": duplicates[:10],
        "same_date_title_dup_count": len(duplicates),
        "importance_min": min(importance_scores) if importance_scores else None,
        "importance_max": max(importance_scores) if importance_scores else None,
        "importance_mean": (
            round(sum(importance_scores) / len(importance_scores), 3)
            if importance_scores else None
        ),
        "importance_n": len(importance_scores),
        "causality_events": causality_count,
    }


async def fetch(client: httpx.AsyncClient, endpoint: str, params: dict[str, Any]) -> tuple[int, dict[str, Any] | None, float]:
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{BASE}/api/v1/history-agent/{endpoint}", params=params)
        elapsed = time.perf_counter() - t0
        if r.status_code != 200:
            return r.status_code, {"error": r.text[:500]}, elapsed
        return r.status_code, r.json(), elapsed
    except Exception as exc:
        return -1, {"error": repr(exc)}, time.perf_counter() - t0


async def run() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    matrix_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for endpoint, label, params in MATRIX:
            print(f"\n=== {label} ({endpoint}?{params}) ===", flush=True)
            cold_status, cold_payload, cold_sec = await fetch(client, endpoint, params)
            warm_status, warm_payload, warm_sec = await fetch(client, endpoint, params)

            sample_path = SAMPLES / f"{label}.json"
            sample_path.write_text(
                json.dumps(cold_payload or {}, ensure_ascii=False, indent=2)
            )

            summary = summarize_payload(cold_payload or {}) if cold_status == 200 else {}
            row = {
                "label": label,
                "endpoint": endpoint,
                "params": params,
                "cold_status": cold_status,
                "warm_status": warm_status,
                "cold_sec": round(cold_sec, 2),
                "warm_sec": round(warm_sec, 3),
                **summary,
            }
            matrix_rows.append(row)
            print(
                f"  cold={cold_status} {cold_sec:6.2f}s  warm={warm_status} {warm_sec:6.3f}s  "
                f"events={summary.get('len_events')} cats={summary.get('category_counts')}",
                flush=True,
            )

    MATRIX_PATH.write_text(json.dumps(matrix_rows, ensure_ascii=False, indent=2))
    print(f"\nMatrix written to {MATRIX_PATH}", flush=True)
    failed = [r for r in matrix_rows if r["cold_status"] != 200 or r["warm_status"] != 200]
    if failed:
        print(f"\n!!! FAILED rows: {len(failed)}", flush=True)
        for r in failed:
            print(f"  - {r['label']}: cold={r['cold_status']} warm={r['warm_status']}", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
