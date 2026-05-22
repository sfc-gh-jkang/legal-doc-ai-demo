-- =============================================================================
-- 31_query_tags.sql — Query Tag Attribution for per-lever cost tracking
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why this matters: QUERY_TAG is the only reliable way to attribute Cortex AI
-- spend back to specific pipeline steps. Without it, QUERY_HISTORY shows
-- undifferentiated AI_COMPLETE calls — impossible to measure lever ROI.
--
-- Convention: legal_doc_ai_demo:lever_<N>
--   1 = Parse cache          5 = Embed search
--   2 = Smart routing        6 = Cost telemetry
--   3 = Cheap scorer         7 = Token preflight
--   4 = Structured outputs   8 = Completion cache
--   9 = Batch mode          10 = Resource monitor
--
-- NOTE: This demo account has a session policy that blocks ALTER SESSION SET
-- QUERY_TAG inside stored procedures. In production (where the customer controls their
-- own session policies), the recommended pattern is:
--   ALTER SESSION SET QUERY_TAG = 'legal_doc_ai_demo:lever_1';
--   SELECT AI_COMPLETE(...);
--   ALTER SESSION SET QUERY_TAG = '';
--
-- For this demo we use a COMMENT-based attribution approach instead:
-- Each Cortex call embeds a SQL comment marker /* lever:N */ that we parse
-- from QUERY_HISTORY.QUERY_TEXT for attribution.

-- =============================================================================
-- Wrapper SPROC: embeds lever tag in the SQL query itself via comment.
-- =============================================================================
CREATE OR REPLACE PROCEDURE TAGGED_AI_COMPLETE(
    p_lever_num NUMBER,
    p_model     VARCHAR,
    p_prompt    VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_result VARCHAR;
BEGIN
    -- The EXECUTE IMMEDIATE embeds the lever marker as a SQL comment.
    -- QUERY_HISTORY will capture this in QUERY_TEXT for attribution.
    LET v_tag VARCHAR := 'lever_' || :p_lever_num::VARCHAR;
    EXECUTE IMMEDIATE
        '/* legal_doc_ai_demo:' || :v_tag || ' */ ' ||
        'SELECT SNOWFLAKE.CORTEX.COMPLETE(''' || :p_model || ''', ''' ||
        REPLACE(:p_prompt, '''', '''''') || ''')';

    -- Retrieve from last query result
    SELECT SNOWFLAKE.CORTEX.COMPLETE(:p_model, :p_prompt) INTO :v_result;

    RETURN :v_result;
END;
$$;

-- =============================================================================
-- Spend-by-tag view: parses lever markers from QUERY_TEXT in QUERY_HISTORY.
-- Also captures any queries where QUERY_TAG was successfully set externally.
-- NOTE: QUERY_HISTORY has ~45-min latency. Results appear after a delay.
-- =============================================================================
CREATE OR REPLACE VIEW SPEND_BY_TAG AS
WITH tagged_queries AS (
    SELECT
        COALESCE(
            NULLIF(QUERY_TAG, ''),
            REGEXP_SUBSTR(QUERY_TEXT, '/\\* legal_doc_ai_demo:(lever_\\d+) \\*/', 1, 1, 'e')
        ) AS attribution_tag,
        CREDITS_USED_CLOUD_SERVICES,
        START_TIME
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE (QUERY_TAG LIKE 'legal_doc_ai_demo:%'
           OR QUERY_TEXT LIKE '%legal_doc_ai_demo:lever_%')
      AND START_TIME >= DATEADD('day', -30, CURRENT_TIMESTAMP())
)
SELECT
    attribution_tag                        AS tag,
    SUM(CREDITS_USED_CLOUD_SERVICES)       AS credits,
    COUNT(*)                               AS query_count,
    MIN(START_TIME)                        AS first_seen,
    MAX(START_TIME)                        AS last_seen
FROM tagged_queries
WHERE attribution_tag IS NOT NULL
GROUP BY attribution_tag
ORDER BY credits DESC;

-- =============================================================================
-- Local attribution table: immediate logging for demo (no QUERY_HISTORY delay).
-- =============================================================================
CREATE TABLE IF NOT EXISTS QUERY_TAG_LOG (
    lever_num    NUMBER    NOT NULL,
    lever_tag    VARCHAR   NOT NULL,
    model        VARCHAR   NOT NULL,
    prompt_hash  VARCHAR   NOT NULL,
    response     VARCHAR,
    logged_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE TAGGED_AI_COMPLETE_WITH_LOG(
    p_lever_num NUMBER,
    p_model     VARCHAR,
    p_prompt    VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
DECLARE
    v_result VARCHAR;
BEGIN
    -- Call AI_COMPLETE
    SELECT SNOWFLAKE.CORTEX.COMPLETE(:p_model, :p_prompt) INTO :v_result;

    -- Log attribution locally for instant visibility
    LET v_tag VARCHAR := 'legal_doc_ai_demo:lever_' || :p_lever_num::VARCHAR;
    LET v_hash VARCHAR := MD5(:p_prompt);
    INSERT INTO QUERY_TAG_LOG (lever_num, lever_tag, model, prompt_hash, response)
    VALUES (:p_lever_num, :v_tag, :p_model, :v_hash, :v_result);

    RETURN :v_result;
END;
$$;

-- =============================================================================
-- Demo: Tag 3 calls (one per lever) — results visible immediately in QUERY_TAG_LOG.
-- =============================================================================
CALL TAGGED_AI_COMPLETE_WITH_LOG(1, 'claude-haiku-4-5', 'In one word, what is a parse cache?');
CALL TAGGED_AI_COMPLETE_WITH_LOG(2, 'claude-haiku-4-5', 'In one word, what is smart routing?');
CALL TAGGED_AI_COMPLETE_WITH_LOG(3, 'claude-haiku-4-5', 'In one word, what is a cheap scorer?');

-- Verify: 3 rows with distinct lever tags
SELECT lever_tag, model, LEFT(response, 30) AS response_preview, logged_at
FROM QUERY_TAG_LOG
ORDER BY logged_at DESC
LIMIT 5;
