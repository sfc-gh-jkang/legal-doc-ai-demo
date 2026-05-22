-- =============================================================================
-- 40_pareto_frontier.sql — Cost vs quality Pareto frontier across models
-- Identifies models that are cheaper than gold WITHOUT unacceptable quality loss
-- =============================================================================

-- Pareto frontier: a model is on the frontier if no other model is both cheaper AND higher quality.
-- This tells the customer: "here are your real options along the cost-quality tradeoff."

CREATE OR REPLACE VIEW SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARETO_FRONTIER_V AS
WITH model_summary AS (
    -- Aggregate per-model quality and cost from the latest model_matrix run
    SELECT
        SPLIT_PART(NOTES, '=', 2) AS MODEL_NAME,
        ROUND(AVG(SIMILARITY_TO_GOLD), 4) AS MEAN_QUALITY,
        ROUND(PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY SIMILARITY_TO_GOLD), 4) AS P10_QUALITY,
        ROUND(AVG(JUDGE_SCORE), 2) AS MEAN_JUDGE_SCORE,
        ROUND(AVG(CASE WHEN AGREEMENT_WITH_GOLD THEN 1.0 ELSE 0.0 END) * 100, 1) AS AGREEMENT_PCT,
        SUM(CREDITS_ESTIMATED) AS TOTAL_CREDITS,
        COUNT(*) AS DOC_COUNT
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC
    WHERE LEVER = 'model'
      AND RUN_ID = (
          SELECT MAX(RUN_ID) FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS WHERE LEVER = 'model'
      )
    GROUP BY MODEL_NAME
),
-- Mark Pareto frontier: on frontier if no other model is BOTH cheaper AND higher quality
frontier AS (
    SELECT
        MS.*,
        NOT EXISTS (
            SELECT 1 FROM model_summary OTHER
            WHERE OTHER.MODEL_NAME != MS.MODEL_NAME
              AND OTHER.TOTAL_CREDITS < MS.TOTAL_CREDITS
              AND OTHER.MEAN_QUALITY > MS.MEAN_QUALITY
        ) AS ON_PARETO_FRONTIER
    FROM model_summary MS
)
SELECT
    F.MODEL_NAME,
    F.MEAN_QUALITY,
    F.P10_QUALITY,
    F.MEAN_JUDGE_SCORE,
    F.AGREEMENT_PCT,
    F.TOTAL_CREDITS,
    F.DOC_COUNT,
    F.ON_PARETO_FRONTIER,
    -- Savings vs gold (claude-4-sonnet)
    ROUND(
        1.0 - (F.TOTAL_CREDITS / NULLIF(
            (SELECT TOTAL_CREDITS FROM frontier WHERE MODEL_NAME = 'claude-4-sonnet'), 0
        )), 4
    ) AS SAVINGS_VS_GOLD_PCT,
    -- Quality delta vs gold
    ROUND(
        F.MEAN_QUALITY - (SELECT MEAN_QUALITY FROM frontier WHERE MODEL_NAME = 'claude-4-sonnet')
    , 4) AS QUALITY_DELTA_VS_GOLD
FROM frontier F
ORDER BY F.TOTAL_CREDITS ASC;
