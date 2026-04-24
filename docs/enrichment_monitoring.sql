-- DB enrichment 누적 건수 모니터링 쿼리
-- 목표: DB hit율 80% 이상 (반복 조회 시)

-- 1. 전체 누적 건수 및 최근 업데이트
SELECT
    COUNT(*)                                              AS total_rows,
    COUNT(DISTINCT ticker)                                AS unique_tickers,
    COUNT(DISTINCT event_type)                            AS unique_event_types,
    MIN(created_at)                                       AS oldest_entry,
    MAX(updated_at)                                       AS latest_update
FROM event_enrichments;

-- 2. 티커별 캐시 건수 (상위 20)
SELECT
    ticker,
    COUNT(*)        AS cached_events,
    MAX(updated_at) AS last_hit
FROM event_enrichments
GROUP BY ticker
ORDER BY cached_events DESC
LIMIT 20;

-- 3. 이벤트 타입별 분포
SELECT
    event_type,
    COUNT(*) AS cnt
FROM event_enrichments
GROUP BY event_type
ORDER BY cnt DESC;

-- 4. 최근 24시간 신규 적재 건수 (LLM 호출 발생 건)
SELECT COUNT(*) AS new_last_24h
FROM event_enrichments
WHERE created_at >= NOW() - INTERVAL '24 hours';

-- 5. causality 있는 이벤트 비율 (SURGE/PLUNGE 분석 커버리지)
SELECT
    COUNT(*)                                          AS total,
    COUNT(*) FILTER (WHERE causality IS NOT NULL)     AS with_causality,
    ROUND(
        COUNT(*) FILTER (WHERE causality IS NOT NULL)::numeric
        / NULLIF(COUNT(*), 0) * 100, 1
    )                                                 AS causality_pct
FROM event_enrichments
WHERE event_type IN ('SURGE', 'PLUNGE');
