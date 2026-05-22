-- =============================================================================
-- 17_token_preflight.sql — Lever 7: Token preflight check
-- Block oversized docs BEFORE burning credits on Cortex calls.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why this matters: A single 600-page contract could consume 500K+ tokens in one
-- AI_PARSE_DOCUMENT + AI_COMPLETE call. Preflight catches these before spend occurs.

CREATE TABLE IF NOT EXISTS PREFLIGHT_LOG (
    file_name        VARCHAR   NOT NULL,
    est_input_tokens NUMBER,
    est_credits      FLOAT,
    decision         VARCHAR,  -- 'allow' | 'warn' | 'block'
    run_at           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Preflight procedure: estimate token count from file size & cached text,
-- then make a gate decision.
CREATE OR REPLACE PROCEDURE PREFLIGHT_CHECK(p_file_name VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
AS
$$
BEGIN
    LET v_text VARCHAR;
    LET v_token_est NUMBER;
    LET v_credit_est FLOAT;
    LET v_decision VARCHAR;

    -- Strategy: check parse cache first (free). If not cached, use file SIZE
    -- from directory listing as proxy (chars ~ 2x compressed file bytes for PDFs).
    SELECT PARSED_TEXT INTO :v_text
    FROM PARSED_CACHE
    WHERE FILENAME = :p_file_name
    LIMIT 1;

    IF (:v_text IS NOT NULL) THEN
        -- Cached text available — estimate tokens as chars/4 (Claude tokenizer avg)
        v_token_est := LENGTH(:v_text) / 4;
    ELSE
        -- No cache hit: use stage file size * 2 as conservative char estimate,
        -- then /4 for token estimate (net: file_size / 2)
        SELECT (SIZE * 2) / 4 INTO :v_token_est
        FROM DIRECTORY(@PDF_STAGE)
        WHERE RELATIVE_PATH = :p_file_name;
    END IF;

    -- Credit estimate: ~0.000003 credits/token for AI_PARSE_DOCUMENT (OCR mode)
    v_credit_est := :v_token_est * 0.000003;

    -- Decision thresholds
    IF (:v_token_est > 500000) THEN
        v_decision := 'block';
    ELSEIF (:v_token_est > 200000) THEN
        v_decision := 'warn';
    ELSE
        v_decision := 'allow';
    END IF;

    -- Log the decision (LET vars used to avoid expressions in VALUES)
    INSERT INTO PREFLIGHT_LOG (file_name, est_input_tokens, est_credits, decision)
    VALUES (:p_file_name, :v_token_est, :v_credit_est, :v_decision);

    RETURN OBJECT_CONSTRUCT(
        'file_name', :p_file_name,
        'est_input_tokens', :v_token_est,
        'est_credits', :v_credit_est,
        'decision', :v_decision
    );
END;
$$;

-- Populate with corpus documents (current 9-doc federal-reg corpus)
CALL PREFLIGHT_CHECK('cfr_title12_part1_banking.pdf');
CALL PREFLIGHT_CHECK('cfr_title16_part1_ftc.pdf');
CALL PREFLIGHT_CHECK('plaw_104publ191_hipaa.pdf');
CALL PREFLIGHT_CHECK('plaw_107publ204_sarbanes_oxley.pdf');
CALL PREFLIGHT_CHECK('plaw_110publ343_eesa.pdf');
CALL PREFLIGHT_CHECK('plaw_111publ148_aca.pdf');
CALL PREFLIGHT_CHECK('plaw_111publ203_dodd_frank.pdf');
CALL PREFLIGHT_CHECK('plaw_115publ232_ndaa.pdf');
CALL PREFLIGHT_CHECK('plaw_118publ31_ndaa_2024.pdf');

-- Verify
SELECT * FROM PREFLIGHT_LOG ORDER BY run_at DESC LIMIT 5;
