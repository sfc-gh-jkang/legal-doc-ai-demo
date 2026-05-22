-- =============================================================================
-- 18_completion_cache.sql — Lever 8: Completion-level cache (AI_COMPLETE dedup)
-- Eliminates redundant LLM calls for repeated prompt+input combinations.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why this matters: the customer's review pipeline often re-scores the same clauses
-- across contract amendments. Caching completions avoids burning credits on
-- identical (model, prompt, input) triples.

CREATE TABLE IF NOT EXISTS COMPLETION_CACHE (
    cache_key         VARCHAR   NOT NULL PRIMARY KEY,
    model             VARCHAR   NOT NULL,
    prompt_hash       VARCHAR   NOT NULL,
    input_hash        VARCHAR   NOT NULL,
    response          VARCHAR,
    completion_tokens NUMBER,
    created_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE COMPLETE_WITH_CACHE(
    p_model  VARCHAR,
    p_prompt VARCHAR,
    p_input  VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
AS
$$
BEGIN
    LET v_cache_key VARCHAR := MD5(:p_model || :p_prompt || :p_input);
    LET v_prompt_hash VARCHAR := MD5(:p_prompt);
    LET v_input_hash VARCHAR := MD5(:p_input);
    LET v_cached_response VARCHAR;
    LET v_fresh_response VARCHAR;
    LET v_token_est NUMBER;

    -- Check cache
    SELECT RESPONSE INTO :v_cached_response
    FROM COMPLETION_CACHE
    WHERE CACHE_KEY = :v_cache_key;

    IF (:v_cached_response IS NOT NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'cached', TRUE,
            'model', :p_model,
            'cache_key', :v_cache_key,
            'response', :v_cached_response
        );
    END IF;

    -- Cache miss: call AI_COMPLETE
    LET v_full_prompt VARCHAR := :p_prompt || '\n\n' || :p_input;
    SELECT SNOWFLAKE.CORTEX.COMPLETE(:p_model, :v_full_prompt)
    INTO :v_fresh_response;

    -- Estimate completion tokens (chars/4)
    v_token_est := LENGTH(:v_fresh_response) / 4;

    -- Store in cache
    INSERT INTO COMPLETION_CACHE (cache_key, model, prompt_hash, input_hash, response, completion_tokens)
    VALUES (:v_cache_key, :p_model, :v_prompt_hash, :v_input_hash, :v_fresh_response, :v_token_est);

    RETURN OBJECT_CONSTRUCT(
        'cached', FALSE,
        'model', :p_model,
        'cache_key', :v_cache_key,
        'response', :v_fresh_response
    );
END;
$$;

-- =============================================================================
-- Demo: Call the same prompt 3 times — first is a miss, 2nd and 3rd are hits.
-- =============================================================================
CALL COMPLETE_WITH_CACHE(
    'claude-haiku-4-5',
    'Classify this clause as: STANDARD, NON-STANDARD, or RISKY. Return one word only.',
    'The parties agree to resolve disputes exclusively through binding arbitration in Colorado.'
);

CALL COMPLETE_WITH_CACHE(
    'claude-haiku-4-5',
    'Classify this clause as: STANDARD, NON-STANDARD, or RISKY. Return one word only.',
    'The parties agree to resolve disputes exclusively through binding arbitration in Colorado.'
);

CALL COMPLETE_WITH_CACHE(
    'claude-haiku-4-5',
    'Classify this clause as: STANDARD, NON-STANDARD, or RISKY. Return one word only.',
    'The parties agree to resolve disputes exclusively through binding arbitration in Colorado.'
);

-- Verify: Should show 1 row (1 unique prompt+input, cached for calls 2 & 3)
SELECT
    cache_key,
    model,
    LEFT(response, 50) AS response_preview,
    completion_tokens,
    created_at
FROM COMPLETION_CACHE
ORDER BY created_at DESC
LIMIT 5;
