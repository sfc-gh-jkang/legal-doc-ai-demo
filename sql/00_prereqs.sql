-- =============================================================================
-- 00_prereqs.sql — One-time account-level prerequisites
-- =============================================================================
-- Run as ACCOUNTADMIN. Sets up the External Access Integration that the
-- Streamlit Container Runtime needs to install Python dependencies from PyPI
-- on first deploy. This must run BEFORE 19_streamlit.sql.
--
-- Idempotent: CREATE OR REPLACE for the integration. Safe to re-run.
--
-- If your role lacks ACCOUNTADMIN, ask your Snowflake admin to run this for you
-- and then GRANT USAGE on the integration to the role that runs deploy.sql.
-- =============================================================================
USE ROLE ACCOUNTADMIN;

-- 1. Network rule: which hosts the Container Runtime is allowed to reach
CREATE OR REPLACE NETWORK RULE LEGAL_DOC_AI_PYPI_NET_RULE
    MODE = EGRESS
    TYPE = HOST_PORT
    VALUE_LIST = ('pypi.org', 'files.pythonhosted.org')
    COMMENT = 'Egress to PyPI for Streamlit Container Runtime dependency resolution';

-- 2. External Access Integration: wraps the network rule for use by Streamlit
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION PYPI_ACCESS_INTEGRATION
    ALLOWED_NETWORK_RULES = (LEGAL_DOC_AI_PYPI_NET_RULE)
    ENABLED = TRUE
    COMMENT = 'PyPI access for legal-doc-ai-demo Streamlit Container Runtime';

-- 3. Grant USAGE so the deploy role / Streamlit owner can attach it
--    (substitute your own role if not using ACCOUNTADMIN as the deploy role)
GRANT USAGE ON INTEGRATION PYPI_ACCESS_INTEGRATION TO ROLE ACCOUNTADMIN;

-- Verify
SHOW INTEGRATIONS LIKE 'PYPI_ACCESS_INTEGRATION';

SELECT 'compile-ok' AS status;
