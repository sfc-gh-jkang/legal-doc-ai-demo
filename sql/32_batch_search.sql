-- =============================================================================
-- Lever 11: Batch Cortex Search (CORTEX_SEARCH_BATCH)
--
-- ⚠️  STRONG WARNING — DOCUMENTATION-ONLY ON THIS DEMO ⚠️
--
-- This file is a REFERENCE PATTERN, not an executable demo lever.
--
-- Per Snowflake docs (https://docs.snowflake.com/en/user-guide/snowflake-cortex/
-- cortex-search/batch-cortex-search):
--
--     "If you need to run fewer than 2,000 queries, you'll typically get faster
--     results using the interactive Cortex Search API rather than batch search."
--
-- Below 2K queries, CORTEX_SEARCH_BATCH is:
--   * SLOWER (job startup latency)
--   * MORE EXPENSIVE (query embedding is NOT free for batch — it IS free for
--     interactive Cortex Search)
--
-- We deliberately do NOT execute the batch path against the demo's 8,576-chunk
-- LEGAL_DOC_AI_SEARCH service because the demo's Q-and-A workload is far below the
-- threshold. Use this file as a reference for when the customer's corpus grows past
-- ~2K queries-per-job (annual entity resolution, contract deduplication,
-- full-corpus eval re-runs across 1,825+ docs × multiple Q-and-A).
-- =============================================================================

USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- -----------------------------------------------------------------------------
-- A. WHEN TO USE BATCH (decision matrix)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW BATCH_SEARCH_DECISION_MATRIX AS
SELECT
    workload                  AS workload_name,
    queries_per_job           AS expected_queries_per_job,
    recommended_api           AS recommended_api,
    rationale                 AS rationale
FROM (
    VALUES
        ('Live Cortex Agent Q-and-A',
         '1-50 per session',
         'INTERACTIVE',
         'Agents need sub-second retrieval. Batch startup latency would break UX. Interactive is also cheaper at this size.'),
        ('Ad-hoc legal research (Tab 4)',
         '1-100 per session',
         'INTERACTIVE',
         'User-facing latency-sensitive. Below 2K threshold by 20x.'),
        ('Quality eval harness (current)',
         '30 grounded Q-and-A',
         'INTERACTIVE',
         'Below 2K. Batch would cost more AND be slower.'),
        ('Quality eval at scale (the customer future)',
         '~18K (1,825 docs x 10 Q-and-A)',
         'BATCH',
         'Above 2K. Batch finishes in minutes on isolated compute vs hours interactive.'),
        ('Annual entity resolution (party names across litigation corpus)',
         '~5K-50K depending on corpus',
         'BATCH',
         'Classic batch use case per Snowflake docs. Offline, throughput-bounded.'),
        ('Contract deduplication sweep',
         '~10K-100K pairs',
         'BATCH',
         'Offline, embarrassingly parallel, high throughput required.'),
        ('Audience matching across legal cases',
         '~2K-20K',
         'BATCH',
         'Right at threshold; batch wins on throughput, interactive wins on simplicity.')
    AS t(workload, queries_per_job, recommended_api, rationale)
);

-- -----------------------------------------------------------------------------
-- B. REFERENCE PATTERN — DO NOT EXECUTE ON THIS DEMO
--
-- The following is the canonical CORTEX_SEARCH_BATCH invocation. It is wrapped
-- in a /* */ block comment so the file deploys cleanly without firing a costly
-- batch job against the demo's small corpus.
-- -----------------------------------------------------------------------------

/*
-- Example: bulk entity-resolution sweep across a hypothetical case docket.
-- Assumes a query_table with one row per inbound case-name to resolve against
-- the canonical LEGAL_DOC_AI_SEARCH service.

WITH case_queries AS (
    SELECT
        case_id,
        inbound_case_name AS query
    FROM the customer_INBOUND_CASES
    WHERE needs_resolution = TRUE
)
SELECT
    q.case_id,
    q.query,
    r.value:CONTENT::STRING       AS matched_chunk,
    r.value:DOCUMENT_TITLE::STRING AS source_doc,
    r.value:SCORE::FLOAT          AS match_score
FROM case_queries AS q,
    LATERAL CORTEX_SEARCH_BATCH(
        service_name => 'SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH',
        query        => q.query,
        limit        => 5,
        options      => OBJECT_CONSTRUCT(
            'replicas', 4   -- higher replicas = faster job, same total $
        )
    ) AS r;
*/

-- -----------------------------------------------------------------------------
-- C. COST COMPONENTS — three buckets, none of them free
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW BATCH_SEARCH_COST_COMPONENTS AS
SELECT
    component_name,
    billed_dimension,
    free_in_interactive_mode,
    free_in_batch_mode,
    notes
FROM (
    VALUES
        ('Serving cost',
         'Search index size x job duration (excludes startup time)',
         TRUE,
         FALSE,
         'Higher replicas finish faster but same total machine-hours. Replicas tune time-to-completion, not $.'),
        ('Query embedding cost',
         'Tokens embedded for input queries',
         TRUE,
         FALSE,
         'Critical: this is FREE in interactive Cortex Search but BILLED in batch. Single biggest reason batch is more expensive at small scale.'),
        ('Warehouse compute',
         'Credits used by the SQL job that calls CORTEX_SEARCH_BATCH',
         FALSE,
         FALSE,
         'Standard warehouse billing. Note: warehouse SIZE does NOT influence batch throughput per docs — service-side compute scales independently.')
    AS t(component_name, billed_dimension, free_in_interactive_mode, free_in_batch_mode, notes)
);

-- -----------------------------------------------------------------------------
-- D. USAGE TRACKING POINTER (for when the customer actually runs batch jobs)
-- -----------------------------------------------------------------------------
-- Per-job billing detail surfaces in:
--   SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_BATCH_QUERY_USAGE_HISTORY
-- (Will be empty on this demo because we never execute a batch job.)

-- -----------------------------------------------------------------------------
-- E. COMPILE GATE
-- -----------------------------------------------------------------------------
SELECT 'compile-ok' AS status, 'Lever 11: Batch Cortex Search' AS lever, 'documentation-only' AS exec_mode;
