-- ─────────────────────────────────────────────────────────────────
-- DB 에 어떤 FOMC 관련 row 가 들어 있는지 진단
--
-- 사용:
--   psql $DATABASE_URL -f scripts/diagnose_fomc_duplicates.sql
--
-- 결과를 그대로 채팅에 붙여 주시면 정확한 cleanup 패턴을 작성해 드립니다.
-- ─────────────────────────────────────────────────────────────────

-- 1) source × title 조합별 카운트 (어떤 release 명이 실제로 들어왔는지)
SELECT
    source,
    title,
    COUNT(*) AS cnt,
    MIN(event_at::date) AS first_date,
    MAX(event_at::date) AS last_date
FROM economic_events
WHERE country = 'US'
  AND (
        title ILIKE '%FOMC%'
     OR title ILIKE '%Federal Open Market%'
     OR title ILIKE '%Press Release%'
     OR title ILIKE '%Projections%'
  )
GROUP BY source, title
ORDER BY source, title;

-- 2) 같은 날짜에 몇 개 row 가 동시에 들어가 있는지 (중복 폭발 정도)
SELECT
    event_at::date AS event_date,
    COUNT(*) AS rows_on_same_date,
    array_agg(source || ':' || title ORDER BY source) AS entries
FROM economic_events
WHERE country = 'US'
  AND (
        title ILIKE '%FOMC%'
     OR title ILIKE '%Federal Open Market%'
     OR title ILIKE '%Press Release%'
     OR title ILIKE '%Projections%'
  )
GROUP BY event_at::date
HAVING COUNT(*) > 1
ORDER BY event_date DESC
LIMIT 30;
