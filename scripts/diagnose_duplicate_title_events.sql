-- ─────────────────────────────────────────────────────────────────
-- (title, event_at) 중복 경제 일정 진단 (read-only)
--
-- 배경:
--  - FRED 의 서로 다른 두 release 가 동일 캘린더 명칭을 발행해
--    economic_events 테이블에 동일 (title, event_at) row 가 2건 이상
--    저장되는 케이스가 있다 (예: "Chicago Fed Advance Retail Trade Summary").
--  - 코드 fix 로 향후 sync 부터는 NewsBackedEventDisambiguator 가 차단하지만,
--    이미 들어간 row 는 본 스크립트로 사전 점검 후
--    scripts/cleanup_duplicate_title_events.py 로 정리한다.
--
-- 사용법:
--   psql $DATABASE_URL -f scripts/diagnose_duplicate_title_events.sql
-- ─────────────────────────────────────────────────────────────────

-- 1) 중복 그룹 요약 (source 별)
SELECT
    source,
    title,
    event_at::date AS event_date,
    COUNT(*) AS duplicate_count,
    ARRAY_AGG(id ORDER BY id) AS ids,
    ARRAY_AGG(source_event_id ORDER BY id) AS source_event_ids
FROM economic_events
GROUP BY source, title, event_at
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, event_date DESC;

-- 2) FRED 만 좁혀서 상세
SELECT
    id,
    source_event_id,
    title,
    event_at,
    importance,
    LEFT(description, 80) AS description_head,
    reference_url
FROM economic_events
WHERE source = 'fred'
  AND (title, event_at) IN (
    SELECT title, event_at
    FROM economic_events
    WHERE source = 'fred'
    GROUP BY title, event_at
    HAVING COUNT(*) > 1
  )
ORDER BY event_at, title, id;

-- 3) 분석 row(event_impact_analyses) 의존성 — CASCADE 로 함께 삭제될 row 수
SELECT
    COUNT(*) AS dependent_analyses
FROM event_impact_analyses
WHERE event_id IN (
    SELECT id FROM economic_events
    WHERE (source, title, event_at) IN (
        SELECT source, title, event_at
        FROM economic_events
        GROUP BY source, title, event_at
        HAVING COUNT(*) > 1
    )
);

-- 4) 알림 row(schedule_notifications) — FK 없음, 별도 삭제 대상
SELECT
    COUNT(*) AS dependent_notifications
FROM schedule_notifications
WHERE event_id IN (
    SELECT id FROM economic_events
    WHERE (source, title, event_at) IN (
        SELECT source, title, event_at
        FROM economic_events
        GROUP BY source, title, event_at
        HAVING COUNT(*) > 1
    )
);
