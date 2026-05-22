-- =============================================================================
-- 99_compare_all.sql — End-to-end benchmark: baseline vs optimized pipeline
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- This script runs both pipelines over the same corpus and prints savings summary.
-- Prerequisites: PDFs uploaded to @PDF_STAGE, all prior SQL files executed.

-- Step 1: Get list of files in stage
CREATE OR REPLACE TEMPORARY TABLE BENCHMARK_FILES AS
SELECT RELATIVE_PATH AS filename FROM DIRECTORY(@PDF_STAGE)
WHERE RELATIVE_PATH LIKE '%.pdf';

-- Step 2: Run baseline on each file (expensive — both modes + claude-4-sonnet scorer)
-- NOTE: In practice, run only on a sample (3-5 files) for demo timing.
-- Full corpus benchmark runs are done via scripts/benchmark.py.
CALL BASELINE_PROCESS_DOC((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 0));
CALL BASELINE_PROCESS_DOC((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 1));
CALL BASELINE_PROCESS_DOC((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 2));

-- Step 3: Run optimized pipeline (cache + smart route + cheap scorer + structured)
-- File 1
CALL SMART_PARSE((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 0));
CALL SCORE_STRUCTURED((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 0));

-- File 2
CALL SMART_PARSE((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 1));
CALL SCORE_STRUCTURED((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 1));

-- File 3
CALL SMART_PARSE((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 2));
CALL SCORE_STRUCTURED((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 2));

-- Step 4: Run cache layer demo — re-process same files (should be instant from cache)
CALL PARSE_WITH_CACHE((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 0), 'LAYOUT');
CALL PARSE_WITH_CACHE((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 1), 'LAYOUT');

-- Step 5: Chunk and embed for search (Lever 5)
CALL CHUNK_AND_EMBED((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 0));
CALL CHUNK_AND_EMBED((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 1));
CALL CHUNK_AND_EMBED((SELECT filename FROM BENCHMARK_FILES LIMIT 1 OFFSET 2));

-- Step 6: Print savings summary
SELECT '=== COST COMPARISON SUMMARY ===' AS section;

SELECT
    COUNT(*) AS docs_compared,
    SUM(total_baseline_credits) AS total_baseline,
    SUM(total_optimized_credits) AS total_optimized,
    SUM(credits_saved) AS total_saved,
    AVG(pct_savings) AS avg_pct_savings
FROM LEVER_SAVINGS;

SELECT '=== PER-DOCUMENT DETAIL ===' AS section;
SELECT * FROM LEVER_SAVINGS;

SELECT '=== SCORER MODEL COMPARISON ===' AS section;
SELECT
    scorer_model,
    COUNT(*) AS files_scored,
    SUM(CASE WHEN agreement_with_gold THEN 1 ELSE 0 END) AS agrees_with_gold,
    AVG(score_tokens) AS avg_tokens,
    AVG(score_credits_est) AS avg_credits
FROM SCORER_AB
GROUP BY scorer_model
ORDER BY avg_credits;

SELECT '=== STRUCTURED vs FREETEXT ===' AS section;
SELECT
    output_mode,
    COUNT(*) AS attempts,
    SUM(CASE WHEN parsed_ok THEN 1 ELSE 0 END) AS success_count,
    AVG(output_tokens) AS avg_tokens,
    SUM(retries) AS total_retries
FROM STRUCTURED_AB
GROUP BY output_mode;

SELECT '=== CACHE HITS ===' AS section;
SELECT
    mode,
    COUNT(*) AS total_entries,
    SUM(parse_tokens) AS total_tokens_cached
FROM PARSED_CACHE
GROUP BY mode;

SELECT '=== SEARCH SERVICE STATUS ===' AS section;
SELECT 'LEGAL_DOC_AI_SEARCH' AS service,
       COUNT(*) AS chunks_indexed
FROM LEGAL_CHUNKS;
