-- =============================================================================
-- 14_structured_outputs.sql — Lever 4: Structured outputs vs free-text
-- 10-20% savings on output tokens by eliminating JSON parse retries.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

CREATE TABLE IF NOT EXISTS STRUCTURED_AB (
    filename        VARCHAR NOT NULL,
    output_mode     VARCHAR NOT NULL,  -- 'structured' or 'freetext'
    parsed_ok       BOOLEAN,
    output_text     VARCHAR,
    output_tokens   NUMBER,
    retries         NUMBER DEFAULT 0,
    tested_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Why this matters: Without structured outputs, LLMs sometimes return malformed JSON
-- requiring retries. Each retry costs tokens. response_format guarantees valid schema.
CREATE OR REPLACE PROCEDURE SCORE_STRUCTURED(filename STRING)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET scoring_prompt VARCHAR;
    LET result VARIANT;
    LET ocr_text VARCHAR;
    LET layout_text VARCHAR;

    SELECT PARSED_TEXT INTO :ocr_text FROM PARSED_CACHE
    WHERE FILENAME = :filename AND MODE = 'OCR' LIMIT 1;

    SELECT PARSED_TEXT INTO :layout_text FROM PARSED_CACHE
    WHERE FILENAME = :filename AND MODE = 'LAYOUT' LIMIT 1;

    scoring_prompt := 'Compare these two PDF extractions. Which is better quality?\n\n'
        || '--- OCR ---\n' || LEFT(NVL(:ocr_text, '[unavailable]'), 3000) || '\n\n'
        || '--- LAYOUT ---\n' || LEFT(NVL(:layout_text, '[unavailable]'), 3000);

    -- Structured output: guaranteed valid JSON schema, no retries needed
    SELECT PARSE_JSON(SNOWFLAKE.CORTEX.AI_COMPLETE(
        'claude-haiku-4-5',
        :scoring_prompt,
        response_format => TYPE OBJECT(best_mode STRING, confidence FLOAT, reasoning STRING),
        show_details => TRUE
    )) INTO :result;

    -- Extract VARIANT path expressions into LET vars (Snowflake SPROC SQL doesn't allow these in VALUES)
    LET output_text VARCHAR := :result:choices[0]:messages::VARCHAR;
    LET output_tokens NUMBER := :result:usage:total_tokens::NUMBER;

    INSERT INTO STRUCTURED_AB (filename, output_mode, parsed_ok, output_text, output_tokens, retries)
    VALUES (
        :filename,
        'structured',
        TRUE,
        :output_text,
        :output_tokens,
        0
    );

    RETURN OBJECT_CONSTRUCT(
        'filename', :filename,
        'mode', 'structured',
        'tokens', :result:usage:total_tokens
    );
END;
$$;

CREATE OR REPLACE PROCEDURE SCORE_FREETEXT(filename STRING)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET scoring_prompt VARCHAR;
    LET result VARIANT;
    LET raw_text VARCHAR;
    LET parsed_ok BOOLEAN := FALSE;
    LET retries NUMBER := 0;
    LET ocr_text VARCHAR;
    LET layout_text VARCHAR;
    LET total_tokens NUMBER := 0;

    SELECT PARSED_TEXT INTO :ocr_text FROM PARSED_CACHE
    WHERE FILENAME = :filename AND MODE = 'OCR' LIMIT 1;

    SELECT PARSED_TEXT INTO :layout_text FROM PARSED_CACHE
    WHERE FILENAME = :filename AND MODE = 'LAYOUT' LIMIT 1;

    scoring_prompt := 'Compare these two PDF extractions. Which is better quality? '
        || 'Return your answer as JSON: {"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}\n\n'
        || '--- OCR ---\n' || LEFT(NVL(:ocr_text, '[unavailable]'), 3000) || '\n\n'
        || '--- LAYOUT ---\n' || LEFT(NVL(:layout_text, '[unavailable]'), 3000);

    -- Free-text: may need retries if JSON is malformed
    REPEAT
        SELECT PARSE_JSON(SNOWFLAKE.CORTEX.AI_COMPLETE(
            'claude-haiku-4-5',
            :scoring_prompt,
            NULL,
            TRUE
        )) INTO :result;

        raw_text := :result:choices[0]:messages::VARCHAR;
        total_tokens := :total_tokens + :result:usage:total_tokens::NUMBER;

        BEGIN
            LET test_parse VARIANT;
            SELECT PARSE_JSON(:raw_text) INTO :test_parse;
            parsed_ok := TRUE;
        EXCEPTION
            WHEN OTHER THEN
                retries := :retries + 1;
                parsed_ok := FALSE;
        END;
    UNTIL (:parsed_ok = TRUE OR :retries >= 3)
    END REPEAT;

    INSERT INTO STRUCTURED_AB (filename, output_mode, parsed_ok, output_text, output_tokens, retries)
    VALUES (:filename, 'freetext', :parsed_ok, :raw_text, :total_tokens, :retries);

    RETURN OBJECT_CONSTRUCT(
        'filename', :filename,
        'mode', 'freetext',
        'parsed_ok', :parsed_ok,
        'retries', :retries,
        'tokens', :total_tokens
    );
END;
$$;
