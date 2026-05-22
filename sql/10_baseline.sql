-- =============================================================================
-- 10_baseline.sql — Simulates the customer's CURRENT (expensive) pattern
-- Runs BOTH OCR + LAYOUT on every doc, then claude-4-sonnet scores & picks.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

CREATE TABLE IF NOT EXISTS BASELINE_RESULTS (
    filename            VARCHAR NOT NULL,
    ocr_text            VARCHAR,
    layout_text         VARCHAR,
    scoring_result_json VARCHAR,
    ocr_tokens          NUMBER,
    layout_tokens       NUMBER,
    score_tokens        NUMBER,
    score_credits_est   FLOAT,
    processed_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Why this matters: This procedure replicates the customer's current pattern
-- of always running both parse modes + an expensive scoring model.
-- The cost baseline from this becomes the denominator for all lever savings.
CREATE OR REPLACE PROCEDURE BASELINE_PROCESS_DOC(filename STRING)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET ocr_result VARCHAR;
    LET layout_result VARCHAR;
    LET scoring_prompt VARCHAR;
    LET score_result VARCHAR;
    LET score_details OBJECT;

    -- Step 1: Parse with OCR mode (expensive for digital docs — unnecessary work)
    SELECT SNOWFLAKE.CORTEX.AI_PARSE_DOCUMENT(
        TO_FILE('@PDF_STAGE', :filename),
        {'mode': 'OCR'}
    ):content::VARCHAR INTO :ocr_result;

    -- Step 2: Parse with LAYOUT mode (expensive for scanned docs — unnecessary work)
    SELECT SNOWFLAKE.CORTEX.AI_PARSE_DOCUMENT(
        TO_FILE('@PDF_STAGE', :filename),
        {'mode': 'LAYOUT'}
    ):content::VARCHAR INTO :layout_result;

    -- Step 3: Use expensive claude-4-sonnet to score both and pick the best
    scoring_prompt := 'You are a document quality assessor. Given two extractions of the same PDF, '
        || 'determine which is higher quality. Consider: text completeness, formatting preservation, '
        || 'table integrity, and readability.\n\n'
        || '--- OCR EXTRACTION ---\n' || LEFT(:ocr_result, 4000) || '\n\n'
        || '--- LAYOUT EXTRACTION ---\n' || LEFT(:layout_result, 4000) || '\n\n'
        || 'Return JSON: {"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}';

    -- Why this matters: claude-4-sonnet is ~10x more expensive than haiku for scoring
    SELECT PARSE_JSON(SNOWFLAKE.CORTEX.AI_COMPLETE(
        'claude-4-sonnet',
        :scoring_prompt,
        NULL,
        TRUE
    )) INTO :score_details;

    score_result := :score_details:choices[0]:messages::VARCHAR;

    -- Snowflake SPROC SQL doesn't allow LENGTH(:var)/N expressions inside VALUES;
    -- compute into LET variables first.
    LET ocr_token_est NUMBER := LENGTH(:ocr_result) / 4;
    LET layout_token_est NUMBER := LENGTH(:layout_result) / 4;
    LET score_total_tokens NUMBER := :score_details:usage:total_tokens::NUMBER;
    LET score_credits FLOAT := :score_details:usage:total_tokens::FLOAT * 0.000012;

    INSERT INTO BASELINE_RESULTS (filename, ocr_text, layout_text, scoring_result_json,
        ocr_tokens, layout_tokens, score_tokens, score_credits_est)
    VALUES (
        :filename,
        :ocr_result,
        :layout_result,
        :score_result,
        :ocr_token_est,
        :layout_token_est,
        :score_total_tokens,
        :score_credits
    );

    RETURN OBJECT_CONSTRUCT(
        'filename', :filename,
        'ocr_len', LENGTH(:ocr_result),
        'layout_len', LENGTH(:layout_result),
        'score_tokens', :score_details:usage:total_tokens,
        'status', 'complete'
    );
END;
$$;
