-- =============================================================================
-- 20_cost_telemetry.sql — Lever 6: Cost visibility via usage history views
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why this matters: You can't optimize what you can't measure.
-- These views surface Cortex AI spend by function, model, and day.

-- Daily roll-up by function and model.
-- NOTE: SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_USAGE_HISTORY is DEPRECATED
-- (last updated Oct 2025 on demo accounts). Use CORTEX_AI_FUNCTIONS_USAGE_HISTORY
-- which has data on/after Jan 5 2026. Schema differs: CREDITS column (not
-- TOKEN_CREDITS), METRICS ARRAY (not TOKENS NUMBER) — extract via METRICS[0]:value.
-- AI_PARSE_DOCUMENT METRICS reports 'pages' unit; AI_COMPLETE/AI_EMBED report 'tokens'.
CREATE OR REPLACE VIEW DAILY_AI_COST AS
SELECT
    DATE_TRUNC('day', START_TIME)::DATE  AS usage_date,
    FUNCTION_NAME,
    MODEL_NAME,
    COUNT(*)                             AS call_count,
    COALESCE(SUM(CASE WHEN ARRAY_SIZE(METRICS) > 0
                      THEN METRICS[0]:value::NUMBER
                      ELSE 0 END), 0)    AS total_tokens,
    SUM(CREDITS)                         AS total_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY
WHERE START_TIME >= DATEADD('day', -90, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 6 DESC;

-- Baseline vs optimized comparison (joins local tracking tables)
CREATE OR REPLACE VIEW LEVER_SAVINGS AS
WITH baseline_cost AS (
    SELECT
        filename,
        (ocr_tokens + layout_tokens) * 0.000003 AS parse_credits,
        score_credits_est AS score_credits,
        (ocr_tokens + layout_tokens) * 0.000003 + score_credits_est AS total_baseline_credits
    FROM BASELINE_RESULTS
),
optimized_cost AS (
    SELECT
        s.filename,
        -- Parse cost: only one mode via smart routing (lever 2), cached on repeat (lever 1)
        s.score_tokens * 0.000001 AS score_credits,  -- haiku pricing (lever 3)
        s.score_tokens * 0.000001 AS total_optimized_credits
    FROM SCORER_AB s
    WHERE s.SCORER_MODEL = 'claude-haiku-4-5'
)
SELECT
    b.filename,
    b.total_baseline_credits,
    COALESCE(o.total_optimized_credits, 0) AS total_optimized_credits,
    b.total_baseline_credits - COALESCE(o.total_optimized_credits, 0) AS credits_saved,
    CASE WHEN b.total_baseline_credits > 0
         THEN (b.total_baseline_credits - COALESCE(o.total_optimized_credits, 0))
              / b.total_baseline_credits * 100
         ELSE 0
    END AS pct_savings
FROM baseline_cost b
LEFT JOIN optimized_cost o ON b.filename = o.filename
ORDER BY credits_saved DESC;

-- Warehouse compute cost for the customer pipeline warehouse
CREATE OR REPLACE VIEW DAILY_WAREHOUSE_COST AS
SELECT
    DATE_TRUNC('day', START_TIME)::DATE AS USAGE_DATE,
    WAREHOUSE_NAME,
    SUM(CREDITS_USED) AS WAREHOUSE_CREDITS
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE WAREHOUSE_NAME = 'SFE_LEGAL_DOC_AI_WH'
  AND START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2;

-- Unified daily cost: AI functions + warehouse compute
CREATE OR REPLACE VIEW DAILY_TOTAL_COST AS
SELECT
    USAGE_DATE,
    'ai_function' AS COST_CATEGORY,
    FUNCTION_NAME AS SOURCE_NAME,
    TOTAL_CREDITS AS CREDITS
FROM DAILY_AI_COST
UNION ALL
SELECT
    USAGE_DATE,
    'warehouse_compute' AS COST_CATEGORY,
    WAREHOUSE_NAME AS SOURCE_NAME,
    WAREHOUSE_CREDITS AS CREDITS
FROM DAILY_WAREHOUSE_COST;
