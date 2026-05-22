-- =============================================================================
-- 01_setup.sql — Database context, schema, warehouse, compute pool, role
-- =============================================================================
-- Note: aws_spcs connection has session policy that blocks USE ROLE.
-- The connection's default role (ACCOUNTADMIN) is used implicitly.
-- USE ROLE SYSADMIN;
USE DATABASE SNOWFLAKE_EXAMPLE;

CREATE SCHEMA IF NOT EXISTS LEGAL_DOC_AI_DEMO;
USE SCHEMA LEGAL_DOC_AI_DEMO;

-- X-Small warehouse to mirror customer's actual sizing
CREATE WAREHOUSE IF NOT EXISTS SFE_LEGAL_DOC_AI_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Legal Doc AI Demo — mirrors customer X-Small sizing';

-- Compute pool for Streamlit Container Runtime (later wave)
CREATE COMPUTE POOL IF NOT EXISTS SFE_LEGAL_DOC_AI_POOL
    MIN_NODES = 1
    MAX_NODES = 2
    INSTANCE_FAMILY = CPU_X64_S
    AUTO_SUSPEND_SECS = 300
    COMMENT = 'Legal Doc AI Demo — Streamlit Container Runtime';

-- Role with Cortex grants (USE ROLE blocked by session policy; create directly).
-- USE ROLE SECURITYADMIN;
CREATE ROLE IF NOT EXISTS LEGAL_DOC_AI_RL;
GRANT ROLE LEGAL_DOC_AI_RL TO ROLE SYSADMIN;

-- USE ROLE ACCOUNTADMIN;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE LEGAL_DOC_AI_RL;

-- USE ROLE SYSADMIN;
GRANT USAGE ON DATABASE SNOWFLAKE_EXAMPLE TO ROLE LEGAL_DOC_AI_RL;
GRANT USAGE ON SCHEMA SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO TO ROLE LEGAL_DOC_AI_RL;
GRANT ALL ON SCHEMA SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO TO ROLE LEGAL_DOC_AI_RL;
GRANT USAGE ON WAREHOUSE SFE_LEGAL_DOC_AI_WH TO ROLE LEGAL_DOC_AI_RL;
