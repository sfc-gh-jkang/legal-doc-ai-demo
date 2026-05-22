-- =============================================================================
-- 11_cache_layer.sql — Lever 1: Parse cache (hash-based dedup)
-- 100% cost savings on repeat/dev-reload runs.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

CREATE TABLE IF NOT EXISTS PARSED_CACHE (
    file_hash       VARCHAR NOT NULL,
    filename        VARCHAR NOT NULL,
    mode            VARCHAR NOT NULL,  -- 'OCR' or 'LAYOUT'
    parsed_text     VARCHAR,
    parsed_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    parse_tokens    NUMBER,
    CONSTRAINT pk_parsed_cache PRIMARY KEY (file_hash, mode)
);

-- Why this matters: the customer re-parses the same 260 documents on every dev reload.
-- A simple hash check eliminates 100% of redundant AI_PARSE_DOCUMENT calls.
CREATE OR REPLACE PROCEDURE PARSE_WITH_CACHE(filename STRING, mode STRING)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET file_hash VARCHAR;
    LET cached_text VARCHAR;
    LET parsed_result VARCHAR;

    -- Compute hash from stage file metadata (MD5 from LIST @stage)
    SELECT MD5(RELATIVE_PATH || '|' || SIZE::VARCHAR || '|' || LAST_MODIFIED::VARCHAR)
    INTO :file_hash
    FROM DIRECTORY(@PDF_STAGE)
    WHERE RELATIVE_PATH = :filename;

    -- Check cache
    SELECT PARSED_TEXT INTO :cached_text
    FROM PARSED_CACHE
    WHERE FILE_HASH = :file_hash AND MODE = :mode;

    IF (:cached_text IS NOT NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'filename', :filename,
            'mode', :mode,
            'source', 'cache',
            'tokens_saved', LENGTH(:cached_text) / 4
        );
    END IF;

    -- Cache miss: call AI_PARSE_DOCUMENT
    SELECT SNOWFLAKE.CORTEX.AI_PARSE_DOCUMENT(
        TO_FILE('@PDF_STAGE', :filename),
        PARSE_JSON('{\"mode\": \"' || :mode || '\"}')
    ):content::VARCHAR INTO :parsed_result;

    -- Store in cache (LENGTH/4 token estimate computed via LET to avoid VALUES expression restriction)
    LET parse_token_est NUMBER := LENGTH(:parsed_result) / 4;
    INSERT INTO PARSED_CACHE (file_hash, filename, mode, parsed_text, parse_tokens)
    VALUES (:file_hash, :filename, :mode, :parsed_result, :parse_token_est);

    RETURN OBJECT_CONSTRUCT(
        'filename', :filename,
        'mode', :mode,
        'source', 'fresh_parse',
        'text_length', LENGTH(:parsed_result)
    );
END;
$$;
