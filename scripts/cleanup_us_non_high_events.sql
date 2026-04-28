-- ─────────────────────────────────────────────────────────────────
-- US 일정 중 importance != 'HIGH' (즉 MEDIUM / LOW) row 전부 삭제
--
-- 배경:
--  - FRED `/releases` 는 press_release=True 인 모든 release 를 끌어와
--    저장하므로, FOMC/CPI/PCE/GDP 같은 핵심 일정 외에도 시장 반응이
--    미미한 부수 release 가 다수 적재된다 (importance=MEDIUM).
--  - 분석 use case 의 default importance_levels 가 ['HIGH'] 라
--    MEDIUM/LOW 는 어차피 분석 대상이 아니지만 DB 에 남아 있어
--    조회·집계·UI 노이즈를 만든다.
--  - 사용자 요청으로 US 일정 중 HIGH 가 아닌 모든 row 를 삭제.
--
-- 안전장치:
--  - BEGIN/ROLLBACK 으로 dry-run, 결과 확인 후 COMMIT
--  - economic_events.id ↔ event_impact_analyses.event_id 는 ON DELETE CASCADE
--  - schedule_notifications 는 FK 가 없어 orphan 정리 별도
--
-- 사용:
--   psql $DATABASE_URL -f scripts/cleanup_us_non_high_events.sql
-- ─────────────────────────────────────────────────────────────────

BEGIN;

-- 1) 삭제 후보 미리보기 (source × importance × 건수)
SELECT
    source,
    importance,
    COUNT(*) AS cnt,
    MIN(event_at::date) AS first_date,
    MAX(event_at::date) AS last_date
FROM economic_events
WHERE country = 'US'
  AND importance <> 'HIGH'
GROUP BY source, importance
ORDER BY source, importance;

-- 2) schedule_notifications orphan 정리 (FK 없음)
DELETE FROM schedule_notifications
WHERE event_id IN (
    SELECT id FROM economic_events
    WHERE country = 'US'
      AND importance <> 'HIGH'
);

-- 3) economic_events 삭제 (event_impact_analyses 는 CASCADE)
DELETE FROM economic_events
WHERE country = 'US'
  AND importance <> 'HIGH';

-- 4) 결과 확인 후 COMMIT 또는 ROLLBACK
-- COMMIT;
-- ROLLBACK;
