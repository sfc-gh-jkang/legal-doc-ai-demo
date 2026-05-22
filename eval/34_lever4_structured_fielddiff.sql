-- =============================================================================
-- 34_lever4_structured_fielddiff.sql — Structured outputs vs free-text + retry rates
-- Lever 4 quality gate: field_identity >= 98%, retry_rate >= 3% (else lever moot)
-- =============================================================================

-- Compare: free-text scorer (may need JSON-parse retries) vs structured scorer
-- (response_format=TYPE OBJECT guarantees valid JSON on first call).

SET run_id = 'structured_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDD_HH24MISS');

INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS (RUN_ID, LEVER, NOTES)
VALUES ($run_id, 'structured', 'Lever 4 structured vs free-text field identity');

-- Step 1: Free-text scoring with retry logic (via SPROC for try/catch)
-- The retry SPROC is defined in sql/14_structured_outputs.sql as:
--   CALL SCORE_WITH_RETRY(filename, max_retries=3) → {best_mode, confidence, reasoning, attempts}

-- Step 2: Structured scoring (guaranteed valid JSON, no retries needed)
-- Uses response_format => 'TYPE OBJECT(best_mode STRING, confidence FLOAT, reasoning STRING)'

-- Assume both results are materialized in STRUCTURED_AB:
--   STRUCTURED_AB (output_mode='freetext'): FILENAME, OUTPUT_TEXT (JSON), RETRIES
--   STRUCTURED_AB (output_mode='structured'): FILENAME, OUTPUT_TEXT (JSON), RETRIES

-- Field-level identity comparison
INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
    (RUN_ID, LEVER, FILENAME, SIMILARITY_TO_GOLD, AGREEMENT_WITH_GOLD, NOTES)
WITH freetext AS (
    SELECT
        FILENAME,
        PARSE_JSON(OUTPUT_TEXT):best_mode::VARCHAR AS BEST_MODE,
        PARSE_JSON(OUTPUT_TEXT):confidence::FLOAT AS CONFIDENCE,
        PARSE_JSON(OUTPUT_TEXT):reasoning::VARCHAR AS REASONING,
        RETRIES + 1 AS ATTEMPTS
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STRUCTURED_AB
    WHERE OUTPUT_MODE = 'freetext'
),
structured AS (
    SELECT
        FILENAME,
        PARSE_JSON(OUTPUT_TEXT):best_mode::VARCHAR AS BEST_MODE,
        PARSE_JSON(OUTPUT_TEXT):confidence::FLOAT AS CONFIDENCE,
        PARSE_JSON(OUTPUT_TEXT):reasoning::VARCHAR AS REASONING
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STRUCTURED_AB
    WHERE OUTPUT_MODE = 'structured'
),
field_comparison AS (
    SELECT
        F.FILENAME,
        -- best_mode identity (exact match)
        (F.BEST_MODE = S.BEST_MODE) AS MODE_IDENTICAL,
        -- confidence identity (within 0.1 tolerance)
        (ABS(F.CONFIDENCE - S.CONFIDENCE) < 0.1) AS CONFIDENCE_CLOSE,
        -- reasoning similarity (AI_SIMILARITY > 0.9 = "identical enough")
        AI_SIMILARITY(F.REASONING, S.REASONING) AS REASONING_SIMILARITY,
        F.ATTEMPTS AS FREE_TEXT_ATTEMPTS
    FROM freetext F
    JOIN structured S
        ON S.FILENAME = F.FILENAME
)
SELECT
    $run_id AS RUN_ID,
    'structured' AS LEVER,
    FC.FILENAME,
    -- Composite identity score: 3 fields, weighted equally
    (CASE WHEN FC.MODE_IDENTICAL THEN 1.0 ELSE 0.0 END
     + CASE WHEN FC.CONFIDENCE_CLOSE THEN 1.0 ELSE 0.0 END
     + CASE WHEN FC.REASONING_SIMILARITY >= 0.9 THEN 1.0 ELSE 0.0 END
    ) / 3.0 AS SIMILARITY_TO_GOLD,
    -- Overall pass: all 3 fields match
    (FC.MODE_IDENTICAL AND FC.CONFIDENCE_CLOSE AND FC.REASONING_SIMILARITY >= 0.9) AS AGREEMENT_WITH_GOLD,
    'mode_match=' || FC.MODE_IDENTICAL::VARCHAR
     || ' conf_close=' || FC.CONFIDENCE_CLOSE::VARCHAR
     || ' reasoning_sim=' || ROUND(FC.REASONING_SIMILARITY, 3)::VARCHAR
     || ' retries=' || (FC.FREE_TEXT_ATTEMPTS - 1)::VARCHAR AS NOTES
FROM field_comparison FC;

-- Retry rate calculation
INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
    (RUN_ID, MODE, RETRY_COUNT_TOTAL, TOTAL_ATTEMPTS, RETRY_RATE_PCT)
SELECT
    $run_id,
    'free_text',
    SUM(RETRIES),
    COUNT(*),
    ROUND(SUM(CASE WHEN RETRIES > 0 THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100, 2)
FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STRUCTURED_AB
WHERE OUTPUT_MODE = 'freetext';

INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
    (RUN_ID, MODE, RETRY_COUNT_TOTAL, TOTAL_ATTEMPTS, RETRY_RATE_PCT)
SELECT
    $run_id,
    'structured',
    0,  -- structured never retries
    COUNT(*),
    0.0
FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STRUCTURED_AB
WHERE OUTPUT_MODE = 'structured';

-- Summary
SELECT
    'Lever 4 Structured Outputs' AS EVAL,
    COUNT(*) AS TOTAL_DOCS,
    ROUND(AVG(SIMILARITY_TO_GOLD) * 100, 1) AS FIELD_IDENTITY_PCT,
    SUM(CASE WHEN AGREEMENT_WITH_GOLD THEN 1 ELSE 0 END) AS ALL_FIELDS_MATCH,
    (SELECT RETRY_RATE_PCT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
     WHERE RUN_ID = $run_id AND MODE = 'free_text') AS FREE_TEXT_RETRY_RATE,
    CASE
        WHEN AVG(SIMILARITY_TO_GOLD) >= 0.98
         AND (SELECT RETRY_RATE_PCT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
              WHERE RUN_ID = $run_id AND MODE = 'free_text') >= 3.0
        THEN 'PASS'
        WHEN (SELECT RETRY_RATE_PCT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
              WHERE RUN_ID = $run_id AND MODE = 'free_text') < 3.0
        THEN 'MOOT (retry rate too low to justify lever)'
        ELSE 'FAIL'
    END AS VERDICT
FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
WHERE RUN_ID = $run_id;
