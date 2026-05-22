-- =============================================================================
-- 13_cheap_scorer.sql — Lever 3: Cheaper scorer models
-- 85-95% savings on the scoring step by using haiku/mistral/llama.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

CREATE TABLE IF NOT EXISTS SCORER_AB (
    filename                VARCHAR NOT NULL,
    scorer_model            VARCHAR NOT NULL,
    scoring_result          VARCHAR,
    agreement_with_gold     BOOLEAN,
    similarity_to_gold      FLOAT,
    score_tokens            NUMBER,
    score_credits_est       FLOAT,
    scored_at               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Why this matters: The scoring prompt is straightforward (pick best mode, rate confidence).
-- Cheaper models agree with claude-4-sonnet >95% of the time at 85-95% lower cost.
CREATE OR REPLACE PROCEDURE RUN_SCORER_MATRIX(filenames ARRAY)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET models ARRAY := ARRAY_CONSTRUCT(
        'claude-4-sonnet',
        'claude-haiku-4-5',
        'claude-sonnet-4-6',
        'mistral-large2',
        'llama3.3-70b'
    );
    LET scoring_prompt VARCHAR;
    LET result VARIANT;
    LET model_name VARCHAR;
    LET fname VARCHAR;
    LET ocr_text VARCHAR;
    LET layout_text VARCHAR;
    LET gold_mode VARCHAR;
    LET rows_inserted NUMBER := 0;
    LET credit_rate FLOAT;

    FOR i IN 0 TO ARRAY_SIZE(:filenames) - 1 DO
        fname := :filenames[:i]::VARCHAR;

        -- Get cached parses (rely on cache from prior levers)
        SELECT PARSED_TEXT INTO :ocr_text
        FROM PARSED_CACHE WHERE FILENAME = :fname AND MODE = 'OCR'
        LIMIT 1;

        SELECT PARSED_TEXT INTO :layout_text
        FROM PARSED_CACHE WHERE FILENAME = :fname AND MODE = 'LAYOUT'
        LIMIT 1;

        -- Build scoring prompt (same prompt for all models — fair comparison)
        scoring_prompt := 'Compare these two PDF extractions and determine which is higher quality. '
            || 'Consider: text completeness, table/list formatting, readability.\n\n'
            || '--- OCR ---\n' || LEFT(NVL(:ocr_text, '[no OCR available]'), 3000) || '\n\n'
            || '--- LAYOUT ---\n' || LEFT(NVL(:layout_text, '[no LAYOUT available]'), 3000);

        -- Get gold reference (claude-4-sonnet result)
        SELECT PARSE_JSON(SCORING_RESULT):best_mode::VARCHAR INTO :gold_mode
        FROM SCORER_AB
        WHERE FILENAME = :fname AND SCORER_MODEL = 'claude-4-sonnet'
        LIMIT 1;

        FOR j IN 0 TO ARRAY_SIZE(:models) - 1 DO
            model_name := :models[:j]::VARCHAR;

            -- Pre-compute credit rate (CASE inside INSERT VALUES doesn't compile in SQL procs)
            IF (:model_name = 'claude-4-sonnet') THEN
                credit_rate := 0.000012;
            ELSEIF (:model_name = 'claude-haiku-4-5') THEN
                credit_rate := 0.000001;
            ELSEIF (:model_name = 'claude-sonnet-4-6') THEN
                credit_rate := 0.000008;
            ELSEIF (:model_name = 'mistral-large2') THEN
                credit_rate := 0.000005;
            ELSEIF (:model_name = 'llama3.3-70b') THEN
                credit_rate := 0.000003;
            ELSE
                credit_rate := 0.000010;
            END IF;

            SELECT PARSE_JSON(SNOWFLAKE.CORTEX.AI_COMPLETE(
                :model_name,
                :scoring_prompt,
                response_format => TYPE OBJECT(best_mode STRING, confidence FLOAT, reasoning STRING),
                show_details => TRUE
            )) INTO :result;

            LET model_choice VARCHAR := :result:choices[0]:messages:best_mode::VARCHAR;
            LET agrees BOOLEAN := (:model_choice = :gold_mode) OR (:gold_mode IS NULL AND :model_name = 'claude-4-sonnet');
            LET result_text VARCHAR := :result:choices[0]:messages::VARCHAR;
            LET result_tokens NUMBER := :result:usage:total_tokens::NUMBER;
            LET result_credits FLOAT := :result:usage:total_tokens::FLOAT * :credit_rate;

            INSERT INTO SCORER_AB (filename, scorer_model, scoring_result,
                agreement_with_gold, score_tokens, score_credits_est)
            VALUES (
                :fname,
                :model_name,
                :result_text,
                :agrees,
                :result_tokens,
                :result_credits
            );

            rows_inserted := :rows_inserted + 1;
        END FOR;
    END FOR;

    RETURN OBJECT_CONSTRUCT('rows_inserted', :rows_inserted, 'models_tested', ARRAY_SIZE(:models));
END;
$$;
