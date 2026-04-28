-- ─────────────────────────────────────────────────────────────────
-- FOMC 회의일 중복 release(FRED 출처) 정리 스크립트
--
-- 배경:
--  - StaticCentralBankEventClient 가 FOMC 회의일에 'FOMC 기준금리 결정'
--    entry(source='central_bank') 를 캐노니컬로 적재한다.
--  - 그러나 FRED 도 같은 날 'FOMC Press Release', 'Summary of Economic
--    Projections', 'FOMC Projections Materials' 등을 별도 row 로 적재해
--    UI 에서 동일 일정이 3~5번 중복 노출되는 버그가 있었다.
--  - 코드 fix(`_FOMC_OVERLAP_KEYWORDS`)로 향후 sync 부터는 차단되지만,
--    이미 저장된 row 는 본 스크립트로 정리한다.
--
-- 안전장치:
--  - 트랜잭션으로 감싸 dry-run 후 COMMIT 또는 ROLLBACK
--  - economic_events.id ↔ event_impact_analyses.event_id 는 ON DELETE CASCADE
--    가 걸려 있으므로 참조 분석 row 도 자동 삭제된다.
--  - schedule_notifications 는 FK 가 없어 orphan 으로 남으므로 별도 삭제.
--
-- 사용법:
--   psql $DATABASE_URL -f scripts/cleanup_fomc_overlap_events.sql
-- ─────────────────────────────────────────────────────────────────

BEGIN;

-- 1) 영향 받는 후보 미리 확인
SELECT
    id,
    source,
    source_event_id,
    title,
    event_at::date AS event_date,
    country
FROM economic_events
WHERE source = 'fred'
  AND (
        title ILIKE '%FOMC Press Release%'
     OR title ILIKE '%Press Release: FOMC%'
     OR title ILIKE '%Press Release: Federal Open Market Committee%'
     OR title ILIKE '%Federal Open Market Committee Press Release%'
     OR title ILIKE '%Summary of Economic Projections%'
     OR title ILIKE '%FOMC Projections Materials%'
  )
ORDER BY event_at;

-- 2) schedule_notifications 의 orphan 정리 (FK 없음 → 명시 삭제)
DELETE FROM schedule_notifications
WHERE event_id IN (
    SELECT id FROM economic_events
    WHERE source = 'fred'
      AND (
            title ILIKE '%FOMC Press Release%'
         OR title ILIKE '%Press Release: FOMC%'
         OR title ILIKE '%Press Release: Federal Open Market Committee%'
         OR title ILIKE '%Federal Open Market Committee Press Release%'
         OR title ILIKE '%Summary of Economic Projections%'
         OR title ILIKE '%FOMC Projections Materials%'
      )
);

-- 3) economic_events 삭제 (event_impact_analyses 는 CASCADE 로 함께 삭제)
DELETE FROM economic_events
WHERE source = 'fred'
  AND (
        title ILIKE '%FOMC Press Release%'
     OR title ILIKE '%Press Release: FOMC%'
     OR title ILIKE '%Press Release: Federal Open Market Committee%'
     OR title ILIKE '%Federal Open Market Committee Press Release%'
     OR title ILIKE '%Summary of Economic Projections%'
     OR title ILIKE '%FOMC Projections Materials%'
  );

-- 4) 결과 확인 후 COMMIT 또는 ROLLBACK
-- COMMIT;
-- ROLLBACK;
