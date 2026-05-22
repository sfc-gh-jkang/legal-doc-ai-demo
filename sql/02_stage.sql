-- =============================================================================
-- 02_stage.sql — SSE-encrypted stage for AI_PARSE_DOCUMENT compatibility
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why SSE: AI_PARSE_DOCUMENT requires SNOWFLAKE_SSE encryption on internal stages.
-- DIRECTORY = TRUE enables file listing and metadata queries.
CREATE OR REPLACE STAGE PDF_STAGE
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Public legal PDFs for the customer cost optimization demo';

ALTER STAGE PDF_STAGE REFRESH;
