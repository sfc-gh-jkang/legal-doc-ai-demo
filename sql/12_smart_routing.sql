-- =============================================================================
-- 12_smart_routing.sql — Lever 2: Smart routing (digital→LAYOUT, scanned→OCR)
-- ~50% savings on parse step by only calling the appropriate mode.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

CREATE TABLE IF NOT EXISTS ROUTING_LOG (
    filename        VARCHAR NOT NULL,
    classified_as   VARCHAR,  -- 'digital' or 'scanned'
    chosen_mode     VARCHAR,  -- 'LAYOUT' or 'OCR'
    confidence      FLOAT,
    routing_method  VARCHAR,  -- 'ai_classify' or 'heuristic'
    routed_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Why this matters: Digital PDFs (text-native) parse perfectly with LAYOUT mode
-- and don't need expensive OCR. Scanned PDFs need OCR. Running both wastes ~50%.
CREATE OR REPLACE PROCEDURE SMART_PARSE(filename STRING)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET sample_text VARCHAR;
    LET classification VARIANT;
    LET doc_type VARCHAR;
    LET chosen_mode VARCHAR;
    LET confidence FLOAT;
    LET parse_result VARCHAR;

    -- Strategy: Try LAYOUT first on a small sample. If it returns substantial text,
    -- the doc is digital. If near-empty, it's scanned and needs OCR.
    -- This heuristic avoids even the cost of AI_CLASSIFY for obvious cases.
    SELECT SNOWFLAKE.CORTEX.AI_PARSE_DOCUMENT(
        TO_FILE('@PDF_STAGE', :filename),
        {'mode': 'LAYOUT'}
    ):content::VARCHAR INTO :sample_text;

    -- Heuristic: digital PDFs produce >500 chars of meaningful text per page
    -- Scanned PDFs produce very little from LAYOUT mode
    IF (LENGTH(:sample_text) > 500) THEN
        -- Digital PDF: LAYOUT extraction is already good, use it directly
        doc_type := 'digital';
        chosen_mode := 'LAYOUT';
        confidence := 0.95;
        parse_result := :sample_text;
    ELSE
        -- Likely scanned: fall back to OCR
        doc_type := 'scanned';
        chosen_mode := 'OCR';
        confidence := 0.85;

        SELECT SNOWFLAKE.CORTEX.AI_PARSE_DOCUMENT(
            TO_FILE('@PDF_STAGE', :filename),
            {'mode': 'OCR'}
        ):content::VARCHAR INTO :parse_result;
    END IF;

    -- Log routing decision for eval
    INSERT INTO ROUTING_LOG (filename, classified_as, chosen_mode, confidence, routing_method)
    VALUES (:filename, :doc_type, :chosen_mode, :confidence, 'heuristic');

    -- Also cache the result (reuse Lever 1 infrastructure)
    LET file_hash VARCHAR;
    LET parse_token_est NUMBER := LENGTH(:parse_result) / 4;
    SELECT MD5(RELATIVE_PATH || '|' || SIZE::VARCHAR || '|' || LAST_MODIFIED::VARCHAR)
    INTO :file_hash
    FROM DIRECTORY(@PDF_STAGE)
    WHERE RELATIVE_PATH = :filename;

    MERGE INTO PARSED_CACHE AS tgt
    USING (SELECT :file_hash AS fh, :filename AS fn, :chosen_mode AS m,
                  :parse_result AS pt, :parse_token_est AS tk) AS src
    ON tgt.FILE_HASH = src.fh AND tgt.MODE = src.m
    WHEN NOT MATCHED THEN
        INSERT (file_hash, filename, mode, parsed_text, parse_tokens)
        VALUES (src.fh, src.fn, src.m, src.pt, src.tk);

    RETURN OBJECT_CONSTRUCT(
        'filename', :filename,
        'doc_type', :doc_type,
        'chosen_mode', :chosen_mode,
        'confidence', :confidence,
        'text_length', LENGTH(:parse_result)
    );
END;
$$;
