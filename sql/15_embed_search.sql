-- =============================================================================
-- 15_embed_search.sql — Lever 5: AI_EMBED + Cortex Search
-- 90%+ savings on downstream Q&A by replacing full-doc re-reads with search.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

CREATE TABLE IF NOT EXISTS LEGAL_CHUNKS (
    chunk_id        NUMBER AUTOINCREMENT,
    chunk_text      VARCHAR,
    doc_name        VARCHAR,
    page_no         NUMBER,
    embedding       VECTOR(FLOAT, 1024),
    chunked_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Why this matters: Instead of feeding entire 200-page PDFs into AI_COMPLETE for Q&A,
-- chunk + embed + search retrieves only relevant passages. 90%+ token savings.
CREATE OR REPLACE PROCEDURE CHUNK_AND_EMBED(filename STRING)
RETURNS OBJECT
LANGUAGE SQL
AS
$$
BEGIN
    LET parsed_text VARCHAR;
    LET chunks_inserted NUMBER := 0;

    -- Pull parsed text from cache (populated by prior levers)
    SELECT PARSED_TEXT INTO :parsed_text FROM PARSED_CACHE
    WHERE FILENAME = :filename
    ORDER BY PARSED_AT DESC
    LIMIT 1;

    IF (:parsed_text IS NULL) THEN
        RETURN OBJECT_CONSTRUCT('error', 'No cached parse found. Run SMART_PARSE first.', 'filename', :filename);
    END IF;

    -- Chunk the text using recursive character splitter
    -- 1500 chars per chunk with 200 char overlap for context continuity
    INSERT INTO LEGAL_CHUNKS (chunk_text, doc_name, page_no, embedding)
    SELECT
        VALUE::VARCHAR AS chunk_text,
        :filename AS doc_name,
        ROW_NUMBER() OVER (ORDER BY INDEX) AS page_no,
        SNOWFLAKE.CORTEX.AI_EMBED('snowflake-arctic-embed-l-v2.0', VALUE::VARCHAR) AS embedding
    FROM TABLE(FLATTEN(
        SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER(:parsed_text, 'markdown', 1500, 200)
    ));

    SELECT COUNT(*) INTO :chunks_inserted FROM LEGAL_CHUNKS WHERE DOC_NAME = :filename;

    RETURN OBJECT_CONSTRUCT(
        'filename', :filename,
        'chunks_created', :chunks_inserted,
        'status', 'complete'
    );
END;
$$;

-- Cortex Search Service: enables natural-language queries over the legal corpus
-- without embedding client-side or managing vector indices manually.
CREATE OR REPLACE CORTEX SEARCH SERVICE LEGAL_DOC_AI_SEARCH
    ON chunk_text
    ATTRIBUTES doc_name, page_no
    WAREHOUSE = SFE_LEGAL_DOC_AI_WH
    TARGET_LAG = '1 hour'
    AS SELECT chunk_text, doc_name, page_no FROM LEGAL_CHUNKS;
