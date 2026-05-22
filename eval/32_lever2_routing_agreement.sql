-- =============================================================================
-- 32_lever2_routing_agreement.sql — Smart routing vs always-both baseline
-- Lever 2 quality gate: agreement >= 95%, p10 similarity >= 0.85, numeric fidelity >= 99%
-- =============================================================================

-- Step 1: Baseline = run BOTH modes, pick best via scorer (gold standard).
-- Step 2: Smart router = pick one mode based on heuristic, run only that.
-- Step 3: Compare routing decision + output quality.

-- This assumes BASELINE_RESULTS and ROUTING_LOG are populated by sql/10_baseline.sql + sql/12_smart_routing.sql.
-- BASELINE_RESULTS columns: FILENAME, OCR_TEXT, LAYOUT_TEXT, SCORING_RESULT_JSON (JSON with best_mode, confidence, reasoning)
-- ROUTING_LOG columns: FILENAME, CHOSEN_MODE, ROUTING_METHOD

SET run_id = 'routing_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDD_HH24MISS');

INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS (RUN_ID, LEVER, NOTES)
VALUES ($run_id, 'routing', 'Lever 2 routing agreement eval');

-- Main comparison: routing decision agreement + text similarity + numeric fidelity
INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
    (RUN_ID, LEVER, FILENAME, SIMILARITY_TO_GOLD, AGREEMENT_WITH_GOLD, NUMERIC_FIDELITY, NOTES)
WITH baseline AS (
    SELECT
        FILENAME,
        PARSE_JSON(SCORING_RESULT_JSON):best_mode::VARCHAR AS BEST_MODE,
        OCR_TEXT,
        LAYOUT_TEXT,
        CASE
            WHEN PARSE_JSON(SCORING_RESULT_JSON):best_mode::VARCHAR = 'OCR' THEN OCR_TEXT
            ELSE LAYOUT_TEXT
        END AS GOLD_TEXT
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.BASELINE_RESULTS
),
routed AS (
    SELECT
        R.FILENAME,
        R.CHOSEN_MODE AS ROUTED_MODE,
        CASE WHEN R.CHOSEN_MODE = 'OCR' THEN BR.OCR_TEXT ELSE BR.LAYOUT_TEXT END AS ROUTED_TEXT,
        R.ROUTING_METHOD AS ROUTING_REASON
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.ROUTING_LOG R
    JOIN SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.BASELINE_RESULTS BR
        ON BR.FILENAME = R.FILENAME
),
-- Extract numeric tokens from both for fidelity check
numeric_extract AS (
    SELECT
        B.FILENAME,
        B.GOLD_TEXT,
        R.ROUTED_TEXT,
        -- Count numeric tokens (dollar amounts, percentages, dates, article refs)
        ARRAY_SIZE(
            REGEXP_SUBSTR_ALL(B.GOLD_TEXT, '\\$[0-9,]+\\.[0-9]{2}|[0-9]+%|\\d{1,2}/\\d{1,2}/\\d{4}|Article \\d+')
        ) AS GOLD_NUMERIC_COUNT,
        ARRAY_SIZE(
            REGEXP_SUBSTR_ALL(R.ROUTED_TEXT, '\\$[0-9,]+\\.[0-9]{2}|[0-9]+%|\\d{1,2}/\\d{1,2}/\\d{4}|Article \\d+')
        ) AS ROUTED_NUMERIC_COUNT
    FROM baseline B
    JOIN routed R ON R.FILENAME = B.FILENAME
)
SELECT
    $run_id AS RUN_ID,
    'routing' AS LEVER,
    B.FILENAME,
    AI_SIMILARITY(B.GOLD_TEXT, R.ROUTED_TEXT) AS SIMILARITY_TO_GOLD,
    (B.BEST_MODE = R.ROUTED_MODE) AS AGREEMENT_WITH_GOLD,
    CASE
        WHEN NE.GOLD_NUMERIC_COUNT = 0 THEN 1.0  -- no numerics to compare
        ELSE LEAST(NE.ROUTED_NUMERIC_COUNT, NE.GOLD_NUMERIC_COUNT)::FLOAT
             / GREATEST(NE.GOLD_NUMERIC_COUNT, 1)::FLOAT
    END AS NUMERIC_FIDELITY,
    'route=' || R.ROUTED_MODE || ' baseline=' || B.BEST_MODE
        || ' reason=' || R.ROUTING_REASON AS NOTES
FROM baseline B
JOIN routed R ON R.FILENAME = B.FILENAME
JOIN numeric_extract NE ON NE.FILENAME = B.FILENAME;

-- Summary statistics
SELECT
    'Lever 2 Routing Agreement' AS EVAL,
    COUNT(*) AS TOTAL_DOCS,
    SUM(CASE WHEN AGREEMENT_WITH_GOLD THEN 1 ELSE 0 END) AS AGREED,
    ROUND(AVG(CASE WHEN AGREEMENT_WITH_GOLD THEN 1.0 ELSE 0.0 END) * 100, 1) AS AGREEMENT_PCT,
    ROUND(AVG(SIMILARITY_TO_GOLD), 4) AS MEAN_SIMILARITY,
    ROUND(PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY SIMILARITY_TO_GOLD), 4) AS P10_SIMILARITY,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY SIMILARITY_TO_GOLD), 4) AS P50_SIMILARITY,
    ROUND(AVG(NUMERIC_FIDELITY) * 100, 1) AS MEAN_NUMERIC_FIDELITY_PCT,
    CASE
        WHEN AVG(CASE WHEN AGREEMENT_WITH_GOLD THEN 1.0 ELSE 0.0 END) >= 0.95
         AND PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY SIMILARITY_TO_GOLD) >= 0.85
         AND AVG(NUMERIC_FIDELITY) >= 0.99
        THEN 'PASS'
        ELSE 'FAIL'
    END AS VERDICT
FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
WHERE RUN_ID = $run_id;
