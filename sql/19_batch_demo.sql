-- =============================================================================
-- 19_batch_demo.sql — Lever 9: Batch (set-based) vs Loop (row-by-row)
-- Single SELECT across N docs vs FOR loop — demonstrates Snowflake's native
-- parallelism advantage for AI function calls.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why this matters: Customers instinctively write FOR loops in stored procedures,
-- calling AI_COMPLETE row-by-row. Snowflake's vectorized execution runs all rows
-- in parallel within a single SELECT — same credits, faster wall-clock time.

CREATE TABLE IF NOT EXISTS BATCH_DEMO_LOG (
    run_id          VARCHAR   NOT NULL,
    mode            VARCHAR   NOT NULL,  -- 'loop' | 'batch'
    doc_count       NUMBER    NOT NULL,
    elapsed_seconds FLOAT,
    est_credits     FLOAT,
    run_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE RUN_BATCH_DEMO()
RETURNS VARIANT
LANGUAGE SQL
AS
$$
BEGIN
    LET v_run_id VARCHAR := MD5(CURRENT_TIMESTAMP()::VARCHAR);
    LET v_doc_count NUMBER;
    LET v_loop_start TIMESTAMP_NTZ;
    LET v_loop_end TIMESTAMP_NTZ;
    LET v_batch_start TIMESTAMP_NTZ;
    LET v_batch_end TIMESTAMP_NTZ;
    LET v_loop_seconds FLOAT;
    LET v_batch_seconds FLOAT;
    LET v_loop_credits FLOAT;
    LET v_batch_credits FLOAT;
    LET v_result VARCHAR;

    -- Count docs
    SELECT COUNT(*) INTO :v_doc_count FROM BASELINE_RESULTS;

    -- =========================================================================
    -- MODE 1: LOOP (row-by-row, sequential AI_COMPLETE calls)
    -- Uses first 500 chars of OCR_TEXT to keep demo fast.
    -- =========================================================================
    v_loop_start := CURRENT_TIMESTAMP();

    LET v_excerpt VARCHAR;
    LET cur CURSOR FOR SELECT LEFT(OCR_TEXT, 500) AS excerpt FROM BASELINE_RESULTS;
    OPEN cur;
    FOR rec IN cur DO
        v_excerpt := rec.excerpt;
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            'claude-haiku-4-5',
            'Summarize this legal excerpt in one sentence: ' || :v_excerpt
        ) INTO :v_result;
    END FOR;
    CLOSE cur;

    v_loop_end := CURRENT_TIMESTAMP();
    v_loop_seconds := TIMESTAMPDIFF('millisecond', :v_loop_start, :v_loop_end) / 1000.0;
    -- Credit estimate: ~500 input tokens + ~50 output tokens per doc at haiku rate
    v_loop_credits := :v_doc_count * 550 * 0.000001;

    LET v_loop_sec_final FLOAT := :v_loop_seconds;
    LET v_loop_cred_final FLOAT := :v_loop_credits;
    INSERT INTO BATCH_DEMO_LOG (run_id, mode, doc_count, elapsed_seconds, est_credits)
    VALUES (:v_run_id, 'loop', :v_doc_count, :v_loop_sec_final, :v_loop_cred_final);

    -- =========================================================================
    -- MODE 2: BATCH (single SELECT, Snowflake parallelizes across rows)
    -- =========================================================================
    v_batch_start := CURRENT_TIMESTAMP();

    CREATE OR REPLACE TEMPORARY TABLE _BATCH_RESULTS AS
    SELECT
        FILENAME,
        SNOWFLAKE.CORTEX.COMPLETE(
            'claude-haiku-4-5',
            'Summarize this legal excerpt in one sentence: ' || LEFT(OCR_TEXT, 500)
        ) AS summary
    FROM BASELINE_RESULTS;

    v_batch_end := CURRENT_TIMESTAMP();
    v_batch_seconds := TIMESTAMPDIFF('millisecond', :v_batch_start, :v_batch_end) / 1000.0;
    -- Same credits as loop (same tokens processed), just faster wall-clock
    v_batch_credits := :v_doc_count * 550 * 0.000001;

    LET v_batch_sec_final FLOAT := :v_batch_seconds;
    LET v_batch_cred_final FLOAT := :v_batch_credits;
    INSERT INTO BATCH_DEMO_LOG (run_id, mode, doc_count, elapsed_seconds, est_credits)
    VALUES (:v_run_id, 'batch', :v_doc_count, :v_batch_sec_final, :v_batch_cred_final);

    -- =========================================================================
    -- Return comparison
    -- =========================================================================
    LET v_speedup FLOAT := CASE WHEN :v_batch_seconds > 0
                                THEN :v_loop_seconds / :v_batch_seconds
                                ELSE 0 END;

    RETURN OBJECT_CONSTRUCT(
        'run_id', :v_run_id,
        'doc_count', :v_doc_count,
        'loop_seconds', :v_loop_seconds,
        'batch_seconds', :v_batch_seconds,
        'speedup_factor', ROUND(:v_speedup, 2),
        'credits_same', TRUE,
        'takeaway', 'Batch mode is ' || ROUND(:v_speedup, 1)::VARCHAR || 'x faster with identical credit spend.'
    );
END;
$$;

-- Execute the demo
CALL RUN_BATCH_DEMO();

-- Verify
SELECT * FROM BATCH_DEMO_LOG ORDER BY run_at DESC LIMIT 4;
