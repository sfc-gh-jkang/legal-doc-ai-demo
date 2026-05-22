-- =============================================================================
-- 09_cross_judge.sql — Cross-family judge bias detection
-- Schema: SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO
-- Purpose: Claude judges Mistral's outputs, Mistral judges Claude's outputs.
--          Detects scoring bias by comparing same-family vs cross-family scores.
-- NOTE: AI_COMPLETE requires literal model name strings — cannot use column refs.
--       Responses wrapped in ```json fences — use REGEXP_REPLACE to strip.
-- =============================================================================

-- 1. Cross-judge results table
CREATE TABLE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE (
    RUN_ID       VARCHAR       NOT NULL,
    SCORER_MODEL VARCHAR       NOT NULL,
    JUDGE_MODEL  VARCHAR       NOT NULL,
    DOC_NAME     VARCHAR       NOT NULL,
    SCORE        FLOAT,
    JUDGED_AT    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- 2. Procedure: run cross-family + same-family judging (4 pairs, one per model-literal)
CREATE OR REPLACE PROCEDURE SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.RUN_CROSS_JUDGE()
RETURNS VARIANT
LANGUAGE SQL
AS
$$
DECLARE
    v_run_id VARCHAR DEFAULT 'cross_judge_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDD_HH24MISS');
    v_summary VARIANT;
BEGIN
    INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS (RUN_ID, LEVER, NOTES)
    VALUES (:v_run_id, 'cross_judge', 'Cross-family judge bias check');

    -- PAIR 1: mistral-large2 judges claude-haiku-4-5 (cross-family)
    INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE
        (RUN_ID, SCORER_MODEL, JUDGE_MODEL, DOC_NAME, SCORE, JUDGED_AT)
    WITH scorer_data AS (
        SELECT E.FILENAME, E.SIMILARITY_TO_GOLD, E.AGREEMENT_WITH_GOLD
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC E
        WHERE E.LEVER = 'model'
          AND E.RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'model')
          AND E.NOTES = 'model=claude-haiku-4-5'
    ),
    doc_context AS (
        SELECT FILENAME, LEFT(PARSED_TEXT, 1500) AS DOC_EXCERPT
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE
    ),
    judged AS (
        SELECT
            SD.FILENAME,
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.AI_COMPLETE(
                    'mistral-large2',
                    'Rate this scorer output 0.0-1.0. Scorer: claude-haiku-4-5. Metrics: similarity=' || COALESCE(SD.SIMILARITY_TO_GOLD::VARCHAR, 'N/A') || ', agreement=' || COALESCE(SD.AGREEMENT_WITH_GOLD::VARCHAR, 'N/A') || '. Doc: ' || LEFT(COALESCE(DC.DOC_EXCERPT, ''), 500) || '. Respond ONLY: {"score": <num>, "reason": "<text>"}'
                ),
                '```json|```|\\n', ''
            ) AS JUDGE_RESPONSE
        FROM scorer_data SD
        LEFT JOIN doc_context DC ON SD.FILENAME = DC.FILENAME
    )
    SELECT :v_run_id, 'claude-haiku-4-5', 'mistral-large2', J.FILENAME,
        TRY_CAST(TRY_PARSE_JSON(TRIM(J.JUDGE_RESPONSE)):score::VARCHAR AS FLOAT),
        CURRENT_TIMESTAMP()
    FROM judged J;

    -- PAIR 2: claude-haiku-4-5 judges mistral-large2 (cross-family)
    INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE
        (RUN_ID, SCORER_MODEL, JUDGE_MODEL, DOC_NAME, SCORE, JUDGED_AT)
    WITH scorer_data AS (
        SELECT E.FILENAME, E.SIMILARITY_TO_GOLD, E.AGREEMENT_WITH_GOLD
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC E
        WHERE E.LEVER = 'model'
          AND E.RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'model')
          AND E.NOTES = 'model=mistral-large2'
    ),
    doc_context AS (
        SELECT FILENAME, LEFT(PARSED_TEXT, 1500) AS DOC_EXCERPT
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE
    ),
    judged AS (
        SELECT
            SD.FILENAME,
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.AI_COMPLETE(
                    'claude-haiku-4-5',
                    'Rate this scorer output 0.0-1.0. Scorer: mistral-large2. Metrics: similarity=' || COALESCE(SD.SIMILARITY_TO_GOLD::VARCHAR, 'N/A') || ', agreement=' || COALESCE(SD.AGREEMENT_WITH_GOLD::VARCHAR, 'N/A') || '. Doc: ' || LEFT(COALESCE(DC.DOC_EXCERPT, ''), 500) || '. Respond ONLY: {"score": <num>, "reason": "<text>"}'
                ),
                '```json|```|\\n', ''
            ) AS JUDGE_RESPONSE
        FROM scorer_data SD
        LEFT JOIN doc_context DC ON SD.FILENAME = DC.FILENAME
    )
    SELECT :v_run_id, 'mistral-large2', 'claude-haiku-4-5', J.FILENAME,
        TRY_CAST(TRY_PARSE_JSON(TRIM(J.JUDGE_RESPONSE)):score::VARCHAR AS FLOAT),
        CURRENT_TIMESTAMP()
    FROM judged J;

    -- PAIR 3: claude-haiku-4-5 judges claude-haiku-4-5 (same-family)
    INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE
        (RUN_ID, SCORER_MODEL, JUDGE_MODEL, DOC_NAME, SCORE, JUDGED_AT)
    WITH scorer_data AS (
        SELECT E.FILENAME, E.SIMILARITY_TO_GOLD, E.AGREEMENT_WITH_GOLD
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC E
        WHERE E.LEVER = 'model'
          AND E.RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'model')
          AND E.NOTES = 'model=claude-haiku-4-5'
    ),
    doc_context AS (
        SELECT FILENAME, LEFT(PARSED_TEXT, 1500) AS DOC_EXCERPT
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE
    ),
    judged AS (
        SELECT
            SD.FILENAME,
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.AI_COMPLETE(
                    'claude-haiku-4-5',
                    'Rate this scorer output 0.0-1.0. Scorer: claude-haiku-4-5. Metrics: similarity=' || COALESCE(SD.SIMILARITY_TO_GOLD::VARCHAR, 'N/A') || ', agreement=' || COALESCE(SD.AGREEMENT_WITH_GOLD::VARCHAR, 'N/A') || '. Doc: ' || LEFT(COALESCE(DC.DOC_EXCERPT, ''), 500) || '. Respond ONLY: {"score": <num>, "reason": "<text>"}'
                ),
                '```json|```|\\n', ''
            ) AS JUDGE_RESPONSE
        FROM scorer_data SD
        LEFT JOIN doc_context DC ON SD.FILENAME = DC.FILENAME
    )
    SELECT :v_run_id, 'claude-haiku-4-5', 'claude-haiku-4-5', J.FILENAME,
        TRY_CAST(TRY_PARSE_JSON(TRIM(J.JUDGE_RESPONSE)):score::VARCHAR AS FLOAT),
        CURRENT_TIMESTAMP()
    FROM judged J;

    -- PAIR 4: mistral-large2 judges mistral-large2 (same-family)
    INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE
        (RUN_ID, SCORER_MODEL, JUDGE_MODEL, DOC_NAME, SCORE, JUDGED_AT)
    WITH scorer_data AS (
        SELECT E.FILENAME, E.SIMILARITY_TO_GOLD, E.AGREEMENT_WITH_GOLD
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC E
        WHERE E.LEVER = 'model'
          AND E.RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'model')
          AND E.NOTES = 'model=mistral-large2'
    ),
    doc_context AS (
        SELECT FILENAME, LEFT(PARSED_TEXT, 1500) AS DOC_EXCERPT
        FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE
    ),
    judged AS (
        SELECT
            SD.FILENAME,
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.AI_COMPLETE(
                    'mistral-large2',
                    'Rate this scorer output 0.0-1.0. Scorer: mistral-large2. Metrics: similarity=' || COALESCE(SD.SIMILARITY_TO_GOLD::VARCHAR, 'N/A') || ', agreement=' || COALESCE(SD.AGREEMENT_WITH_GOLD::VARCHAR, 'N/A') || '. Doc: ' || LEFT(COALESCE(DC.DOC_EXCERPT, ''), 500) || '. Respond ONLY: {"score": <num>, "reason": "<text>"}'
                ),
                '```json|```|\\n', ''
            ) AS JUDGE_RESPONSE
        FROM scorer_data SD
        LEFT JOIN doc_context DC ON SD.FILENAME = DC.FILENAME
    )
    SELECT :v_run_id, 'mistral-large2', 'mistral-large2', J.FILENAME,
        TRY_CAST(TRY_PARSE_JSON(TRIM(J.JUDGE_RESPONSE)):score::VARCHAR AS FLOAT),
        CURRENT_TIMESTAMP()
    FROM judged J;

    -- Return summary using pre-aggregated subquery (avoids nested agg error)
    v_summary := (
        SELECT ARRAY_AGG(obj) FROM (
            SELECT OBJECT_CONSTRUCT(
                'scorer', SCORER_MODEL,
                'judge', JUDGE_MODEL,
                'avg_score', ROUND(AVG(SCORE), 4),
                'n', COUNT(*)
            ) AS obj
            FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE
            WHERE RUN_ID = :v_run_id
            GROUP BY SCORER_MODEL, JUDGE_MODEL
        )
    );

    RETURN :v_summary;
END;
$$;

-- 3. View: Bias report — same-family vs cross-family score comparison per scorer
--    BIAS_DELTA = same_family_score - cross_family_score
--    Positive delta means same-family judges score higher (self-preference bias).
--    |delta| < 0.15 is ACCEPTABLE; > 0.15 is HIGH_BIAS.
CREATE OR REPLACE VIEW SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE_BIAS_REPORT AS
WITH latest_run AS (
    SELECT MAX(RUN_ID) AS RUN_ID
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE
),
scores AS (
    SELECT
        CJ.SCORER_MODEL,
        CJ.JUDGE_MODEL,
        CJ.SCORE,
        CASE
            WHEN CJ.SCORER_MODEL LIKE 'claude%' AND CJ.JUDGE_MODEL LIKE 'claude%' THEN 'same_family'
            WHEN CJ.SCORER_MODEL LIKE 'mistral%' AND CJ.JUDGE_MODEL LIKE 'mistral%' THEN 'same_family'
            ELSE 'cross_family'
        END AS JUDGE_TYPE
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_CROSS_JUDGE CJ
    WHERE CJ.RUN_ID = (SELECT RUN_ID FROM latest_run)
)
SELECT
    SCORER_MODEL,
    ROUND(AVG(CASE WHEN JUDGE_TYPE = 'same_family' THEN SCORE END), 4) AS SAME_FAMILY_SCORE,
    ROUND(AVG(CASE WHEN JUDGE_TYPE = 'cross_family' THEN SCORE END), 4) AS CROSS_FAMILY_SCORE,
    ROUND(
        COALESCE(AVG(CASE WHEN JUDGE_TYPE = 'same_family' THEN SCORE END), 0) -
        COALESCE(AVG(CASE WHEN JUDGE_TYPE = 'cross_family' THEN SCORE END), 0),
    4) AS BIAS_DELTA,
    CASE
        WHEN ABS(COALESCE(AVG(CASE WHEN JUDGE_TYPE = 'same_family' THEN SCORE END), 0) -
                 COALESCE(AVG(CASE WHEN JUDGE_TYPE = 'cross_family' THEN SCORE END), 0)) < 0.15
        THEN 'ACCEPTABLE'
        ELSE 'HIGH_BIAS'
    END AS BIAS_VERDICT,
    COUNT(*) AS TOTAL_JUDGMENTS
FROM scores
GROUP BY SCORER_MODEL;

-- 4. Execute cross-judge
CALL SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.RUN_CROSS_JUDGE();
