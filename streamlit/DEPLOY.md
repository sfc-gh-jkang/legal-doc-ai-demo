# Deploying the Legal Doc AI Streamlit App

## Prerequisites

- Compute pool `SFE_LEGAL_DOC_AI_POOL` running (created by `sql/01_setup.sql`)
- Warehouse `SFE_LEGAL_DOC_AI_WH` available
- All SQL files in `sql/` deployed (10-20 series)
- Stage `@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE` created

## Deploy Commands

```sql
USE ROLE SYSADMIN;
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- 1. Create the stage for Streamlit assets (if not exists)
CREATE STAGE IF NOT EXISTS STREAMLIT_STAGE
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

-- 2. Upload app files to stage
-- Run from the streamlit/ directory:
```

```bash
cd /Users/jkang/Documents/vscode/legal-doc-ai-demo/streamlit

snow stage put app.py @SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE/ \
    --overwrite -c aws_spcs

snow stage put pyproject.toml @SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE/ \
    --overwrite -c aws_spcs

snow stage put snowflake.yml @SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE/ \
    --overwrite -c aws_spcs
```

```sql
-- 3. Create (or replace) the Streamlit app
CREATE OR REPLACE STREAMLIT SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_APP
    FROM '@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE'
    MAIN_FILE = 'app.py'
    QUERY_WAREHOUSE = SFE_LEGAL_DOC_AI_WH
    TITLE = 'Legal Doc AI — Cost & Quality'
    COMMENT = 'Legal Doc AI PDF cost optimization demo — 6 levers'
    RUNTIME_VERSION = 'SYSTEM$ST_CONTAINER_RUNTIME_PY3_11'
    COMPUTE_POOL = SFE_LEGAL_DOC_AI_POOL
    EXTERNAL_ACCESS_INTEGRATIONS = (PYPI_ACCESS_INTEGRATION);

-- 4. Force container restart to pick up new code
ALTER STREAMLIT SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_APP
    ADD LIVE VERSION FROM LAST;

-- 5. Verify
SHOW STREAMLITS LIKE 'LEGAL_DOC_AI_APP' IN SCHEMA SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO;
```

## Redeployment (code changes only)

After modifying `app.py`:

```bash
# Upload updated file
snow stage put app.py @SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE/ \
    --overwrite -c aws_spcs
```

```sql
-- IMPORTANT: ALTER STREAMLIT COMMIT is NOT enough for Container Runtime.
-- Must CREATE OR REPLACE + ADD LIVE VERSION to force container restart.
CREATE OR REPLACE STREAMLIT SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_APP
    FROM '@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.STREAMLIT_STAGE'
    MAIN_FILE = 'app.py'
    QUERY_WAREHOUSE = SFE_LEGAL_DOC_AI_WH
    TITLE = 'Legal Doc AI — Cost & Quality'
    RUNTIME_VERSION = 'SYSTEM$ST_CONTAINER_RUNTIME_PY3_11'
    COMPUTE_POOL = SFE_LEGAL_DOC_AI_POOL
    EXTERNAL_ACCESS_INTEGRATIONS = (PYPI_ACCESS_INTEGRATION);

ALTER STREAMLIT SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_APP
    ADD LIVE VERSION FROM LAST;
```

## Granting Access

```sql
GRANT USAGE ON STREAMLIT SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_APP
    TO ROLE LEGAL_DOC_AI_RL;
```

## Troubleshooting

- **App shows blank/errors after deploy**: Wait 30-60s for container to restart.
  Check: `SELECT SYSTEM$GET_SERVICE_STATUS('LEGAL_DOC_AI_APP');`
- **"Session token not found"** in Tab 4: App must run in Container Runtime (not warehouse mode).
  The OAuth token at `/snowflake/session/token` is only mounted in container environments.
- **Cost data empty** in Tab 3: `CORTEX_FUNCTIONS_USAGE_HISTORY` has ~3hr lag. Process
  some docs and wait before expecting data.
- **Eval tables empty** in Tab 5: Run `eval/30-50` SQL files first to populate eval results.
