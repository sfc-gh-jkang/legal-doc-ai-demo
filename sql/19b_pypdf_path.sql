-- =============================================================================
-- 19b_pypdf_path.sql — Lever 7b: Free pypdf extraction as first-pass filter
-- Schema: SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO
-- Purpose: Track which PDFs can be extracted via pypdf (free) vs requiring
--          AI_PARSE_DOCUMENT (costly). Saves ~0.0035 credits/page on readable PDFs.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- 1. Extraction path log table
CREATE TABLE IF NOT EXISTS EXTRACTION_PATH_LOG (
    FILE_NAME         VARCHAR       NOT NULL,
    PATH_USED         VARCHAR       NOT NULL,  -- 'pypdf-success' | 'requires-ai-parse'
    CHAR_COUNT        NUMBER,
    EST_CREDITS_SAVED FLOAT,
    RUN_AT            TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- 2. Summary view: extraction path distribution and cost savings
CREATE OR REPLACE VIEW the customer_EXTRACTION_PATH_SUMMARY AS
SELECT
    PATH_USED,
    COUNT(*) AS DOC_COUNT,
    SUM(CHAR_COUNT) AS TOTAL_CHARS,
    ROUND(SUM(EST_CREDITS_SAVED), 4) AS TOTAL_CREDITS_SAVED,
    ROUND(AVG(CHAR_COUNT), 0) AS AVG_CHARS_PER_DOC,
    MAX(RUN_AT) AS LAST_RUN
FROM EXTRACTION_PATH_LOG
GROUP BY PATH_USED
ORDER BY DOC_COUNT DESC;

-- 3. Seed with known corpus data (from BASELINE_RESULTS which has OCR text)
-- All 5 legal PDFs have extensive text content and are English-readable,
-- so they would all classify as pypdf-success in production.
-- Estimate pages from OCR_TOKENS (avg ~500 tokens/page for legal docs).
INSERT INTO EXTRACTION_PATH_LOG (FILE_NAME, PATH_USED, CHAR_COUNT, EST_CREDITS_SAVED)
SELECT
    FILENAME,
    CASE
        WHEN LENGTH(OCR_TEXT) > 1000 THEN 'pypdf-success'
        ELSE 'requires-ai-parse'
    END AS PATH_USED,
    LENGTH(OCR_TEXT) AS CHAR_COUNT,
    CASE
        WHEN LENGTH(OCR_TEXT) > 1000 THEN CEIL(OCR_TOKENS / 500.0) * 0.0035
        ELSE 0
    END AS EST_CREDITS_SAVED
FROM BASELINE_RESULTS;
