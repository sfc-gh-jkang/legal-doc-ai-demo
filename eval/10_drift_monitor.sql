-- =============================================================================
-- 10_drift_monitor.sql — Eval drift monitor: baseline tracking + weekly alert
-- Schema: SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- 1. Baseline table: stores last-known-good metric per lever
CREATE TABLE IF NOT EXISTS EVAL_DRIFT_BASELINE (
    LEVER_NUM       NUMBER        NOT NULL,
    METRIC          VARCHAR       NOT NULL,
    BASELINE_VALUE  FLOAT         NOT NULL,
    BASELINE_RUN_ID VARCHAR       NOT NULL,
    SET_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- 2. Procedure: snapshot current EVAL_SUMMARY_V verdicts into baseline
CREATE OR REPLACE PROCEDURE SET_DRIFT_BASELINE()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_count NUMBER;
BEGIN
    -- Clear existing baseline
    DELETE FROM EVAL_DRIFT_BASELINE;

    -- Insert current metric per lever from EVAL_SUMMARY_V
    INSERT INTO EVAL_DRIFT_BASELINE (LEVER_NUM, METRIC, BASELINE_VALUE, BASELINE_RUN_ID, SET_AT)
    SELECT
        ROW_NUMBER() OVER (ORDER BY LEVER) AS LEVER_NUM,
        LEVER,
        COALESCE(MIN_SIMILARITY, 0) AS BASELINE_VALUE,
        (SELECT MAX(RUN_ID) FROM EVAL_RUNS WHERE EVAL_RUNS.LEVER = s.LEVER) AS BASELINE_RUN_ID,
        CURRENT_TIMESTAMP()
    FROM EVAL_SUMMARY_V s;

    SELECT COUNT(*) INTO v_count FROM EVAL_DRIFT_BASELINE;
    RETURN 'Baseline set: ' || v_count::VARCHAR || ' levers captured at ' || CURRENT_TIMESTAMP()::VARCHAR;
END;
$$;

-- 3. Procedure: check current metrics against baseline, return drift report
CREATE OR REPLACE PROCEDURE CHECK_DRIFT()
RETURNS VARIANT
LANGUAGE SQL
AS
$$
DECLARE
    v_result VARIANT;
BEGIN
    LET drift_report VARIANT := (
        SELECT ARRAY_AGG(OBJECT_CONSTRUCT(
            'lever', b.METRIC,
            'lever_num', b.LEVER_NUM,
            'baseline', b.BASELINE_VALUE,
            'current', COALESCE(s.MIN_SIMILARITY, 0),
            'drift_pct', CASE
                WHEN b.BASELINE_VALUE = 0 THEN 0
                ELSE ROUND(((b.BASELINE_VALUE - COALESCE(s.MIN_SIMILARITY, 0)) / b.BASELINE_VALUE) * 100, 2)
            END,
            'alert', CASE
                WHEN b.BASELINE_VALUE = 0 THEN 'OK'
                WHEN ((b.BASELINE_VALUE - COALESCE(s.MIN_SIMILARITY, 0)) / b.BASELINE_VALUE) * 100 > 10 THEN 'BREACH'
                WHEN ((b.BASELINE_VALUE - COALESCE(s.MIN_SIMILARITY, 0)) / b.BASELINE_VALUE) * 100 > 5 THEN 'WARN'
                ELSE 'OK'
            END
        )) AS DRIFT_ARRAY
        FROM EVAL_DRIFT_BASELINE b
        LEFT JOIN EVAL_SUMMARY_V s ON b.METRIC = s.LEVER
    );

    v_result := drift_report;
    RETURN v_result;
END;
$$;

-- 4. Weekly task (SUSPENDED by default — resume when ready for production)
CREATE OR REPLACE TASK DRIFT_WEEKLY
    WAREHOUSE = SFE_LEGAL_DOC_AI_WH
    SCHEDULE  = 'USING CRON 0 8 * * MON America/Los_Angeles'
AS
    CALL CHECK_DRIFT();

-- ALTER TASK DRIFT_WEEKLY RESUME;  -- Uncomment to activate

-- 5. View: latest drift check results (calls the proc and presents as relational)
CREATE OR REPLACE VIEW EVAL_DRIFT_LATEST AS
SELECT
    b.LEVER_NUM,
    b.METRIC AS LEVER,
    b.BASELINE_VALUE,
    COALESCE(s.MIN_SIMILARITY, 0) AS CURRENT_VALUE,
    CASE
        WHEN b.BASELINE_VALUE = 0 THEN 0
        ELSE ROUND(((b.BASELINE_VALUE - COALESCE(s.MIN_SIMILARITY, 0)) / b.BASELINE_VALUE) * 100, 2)
    END AS DRIFT_PCT,
    CASE
        WHEN b.BASELINE_VALUE = 0 THEN 'OK'
        WHEN ((b.BASELINE_VALUE - COALESCE(s.MIN_SIMILARITY, 0)) / b.BASELINE_VALUE) * 100 > 10 THEN 'BREACH'
        WHEN ((b.BASELINE_VALUE - COALESCE(s.MIN_SIMILARITY, 0)) / b.BASELINE_VALUE) * 100 > 5 THEN 'WARN'
        ELSE 'OK'
    END AS ALERT_STATUS,
    b.SET_AT AS BASELINE_SET_AT,
    b.BASELINE_RUN_ID
FROM EVAL_DRIFT_BASELINE b
LEFT JOIN EVAL_SUMMARY_V s ON b.METRIC = s.LEVER
ORDER BY b.LEVER_NUM;

-- 6. Initialize baseline
CALL SET_DRIFT_BASELINE();
