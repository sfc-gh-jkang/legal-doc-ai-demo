-- =============================================================================
-- 50_eval_summary.sql — Top-level pass/fail summary per lever
-- Used by Streamlit "Quality vs Cost" tab
-- =============================================================================

CREATE OR REPLACE VIEW SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_SUMMARY_V AS
WITH lever1 AS (
    -- Cache: AI_SIMILARITY = 1.000 for all docs
    SELECT
        'cache' AS LEVER,
        '1 - Parse Cache' AS LEVER_NAME,
        COUNT(*) AS TOTAL_DOCS,
        SUM(CASE WHEN AGREEMENT_WITH_GOLD THEN 1 ELSE 0 END) AS PASSED_DOCS,
        ROUND(MIN(SIMILARITY_TO_GOLD), 4) AS MIN_SIMILARITY,
        CASE WHEN MIN(SIMILARITY_TO_GOLD) = 1.0 THEN 'PASS' ELSE 'FAIL' END AS VERDICT,
        'All cached outputs byte-identical to fresh parse' AS GATE_DESCRIPTION
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
    WHERE LEVER = 'cache'
      AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'cache')
),
lever2 AS (
    -- Routing: agreement >= 95% AND p10 >= 0.85 AND numeric_fidelity >= 99%
    SELECT
        'routing' AS LEVER,
        '2 - Smart Routing' AS LEVER_NAME,
        COUNT(*) AS TOTAL_DOCS,
        SUM(CASE WHEN AGREEMENT_WITH_GOLD THEN 1 ELSE 0 END) AS PASSED_DOCS,
        ROUND(PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY SIMILARITY_TO_GOLD), 4) AS MIN_SIMILARITY,
        CASE
            WHEN AVG(CASE WHEN AGREEMENT_WITH_GOLD THEN 1.0 ELSE 0.0 END) >= 0.95
             AND PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY SIMILARITY_TO_GOLD) >= 0.85
             AND AVG(COALESCE(NUMERIC_FIDELITY, 1.0)) >= 0.99
            THEN 'PASS'
            ELSE 'FAIL'
        END AS VERDICT,
        'Routing agreement>=95%, p10 similarity>=0.85, numeric fidelity>=99%' AS GATE_DESCRIPTION
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
    WHERE LEVER = 'routing'
      AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'routing')
),
lever3 AS (
    -- Model: Pareto non-empty AND >= 1 cheaper model on it
    SELECT
        'model' AS LEVER,
        '3 - Cheaper Scorer' AS LEVER_NAME,
        (SELECT COUNT(*) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARETO_FRONTIER_V) AS TOTAL_DOCS,
        (SELECT COUNT(*) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARETO_FRONTIER_V
         WHERE ON_PARETO_FRONTIER AND MODEL_NAME != 'claude-4-sonnet') AS PASSED_DOCS,
        (SELECT MIN(MEAN_QUALITY) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARETO_FRONTIER_V
         WHERE ON_PARETO_FRONTIER) AS MIN_SIMILARITY,
        CASE
            WHEN (SELECT COUNT(*) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARETO_FRONTIER_V
                  WHERE ON_PARETO_FRONTIER AND MODEL_NAME != 'claude-4-sonnet') >= 1
            THEN 'PASS'
            ELSE 'FAIL'
        END AS VERDICT,
        'Pareto frontier non-empty with >=1 cheaper-than-gold model' AS GATE_DESCRIPTION
),
lever4 AS (
    -- Structured: field_identity >= 98% AND retry_rate >= 3%
    SELECT
        'structured' AS LEVER,
        '4 - Structured Outputs' AS LEVER_NAME,
        COUNT(*) AS TOTAL_DOCS,
        SUM(CASE WHEN AGREEMENT_WITH_GOLD THEN 1 ELSE 0 END) AS PASSED_DOCS,
        ROUND(AVG(SIMILARITY_TO_GOLD), 4) AS MIN_SIMILARITY,
        CASE
            WHEN AVG(SIMILARITY_TO_GOLD) >= 0.98
             AND (SELECT RETRY_RATE_PCT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
                  WHERE MODE = 'free_text'
                    AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'structured')
                 ) >= 3.0
            THEN 'PASS'
            WHEN (SELECT RETRY_RATE_PCT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES
                  WHERE MODE = 'free_text'
                    AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'structured')
                 ) < 3.0
            THEN 'MOOT'
            ELSE 'FAIL'
        END AS VERDICT,
        'Field identity>=98% AND free-text retry rate>=3%' AS GATE_DESCRIPTION
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
    WHERE LEVER = 'structured'
      AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'structured')
),
lever5 AS (
    -- Retrieval: recall@5 >= 0.85, MRR >= 0.7, end-to-end >= 90% of baseline
    SELECT
        'retrieval' AS LEVER,
        '5 - Retrieval (Cortex Search)' AS LEVER_NAME,
        (SELECT COUNT(*) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
         WHERE RETRIEVAL_METHOD = 'cortex_search'
           AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval')
        ) AS TOTAL_DOCS,
        (SELECT SUM(CASE WHEN RECALL_AT_5 >= 0.85 AND MRR >= 0.7 THEN 1 ELSE 0 END)
         FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
         WHERE RETRIEVAL_METHOD = 'cortex_search'
           AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval')
        ) AS PASSED_DOCS,
        (SELECT ROUND(AVG(SIMILARITY_TO_GOLD), 4) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
         WHERE RETRIEVAL_METHOD = 'cortex_search'
           AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval')
        ) AS MIN_SIMILARITY,
        CASE
            WHEN (SELECT AVG(RECALL_AT_5) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
                  WHERE RETRIEVAL_METHOD = 'cortex_search'
                    AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval')
                 ) >= 0.85
             AND (SELECT AVG(MRR) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
                  WHERE RETRIEVAL_METHOD = 'cortex_search'
                    AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval')
                 ) >= 0.7
             AND (SELECT AVG(SIMILARITY_TO_GOLD) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
                  WHERE RETRIEVAL_METHOD = 'cortex_search'
                    AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval')
                 ) >= 0.90 * (SELECT AVG(SIMILARITY_TO_GOLD) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS
                              WHERE RETRIEVAL_METHOD = 'full_doc_stuff'
                                AND RUN_ID = (SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'retrieval'))
            THEN 'PASS'
            ELSE 'FAIL'
        END AS VERDICT,
        'Recall@5>=0.85, MRR>=0.7, E2E similarity>=90% of full-doc baseline' AS GATE_DESCRIPTION
)
SELECT * FROM lever1
UNION ALL SELECT * FROM lever2
UNION ALL SELECT * FROM lever3
UNION ALL SELECT * FROM lever4
UNION ALL SELECT * FROM lever5;
