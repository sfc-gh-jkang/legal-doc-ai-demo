# AGENTS.md — Legal Doc AI Demo

## Connection Routing
- All SQL: connection `aws_spcs` (SFSENORTHAMERICA-JKANG_AWS_US_EAST_1_1)
- Role context: SYSADMIN for DDL, LEGAL_DOC_AI_RL for runtime
- Warehouse: `SFE_LEGAL_DOC_AI_WH` (X-Small)

## Naming Conventions
- Database: `SNOWFLAKE_EXAMPLE`
- Schema: `LEGAL_DOC_AI_DEMO`
- All objects unqualified in SQL files (USE context set in 01_setup.sql)
- Stage: `PDF_STAGE` (SSE encrypted, directory enabled)
- Tables: UPPER_SNAKE_CASE
- Sprocs: UPPER_SNAKE_CASE matching their lever

## Key SQL Patterns
- `AI_PARSE_DOCUMENT(TO_FILE('@PDF_STAGE', filename), {'mode':'LAYOUT'})` — always qualify stage with schema
- `AI_COMPLETE('model', prompt, NULL, TRUE)` — 4th arg = show_details for token tracking
- `AI_COMPLETE('model', prompt, response_format => TYPE OBJECT(...))` — structured output
- `AI_EMBED('snowflake-arctic-embed-l-v2.0', text)` — 1024-dim embeddings
- `SPLIT_TEXT_RECURSIVE_CHARACTER(text, 'markdown', 1500, 200)` — chunking
- `AI_CLASSIFY(text, ['label1', 'label2'])` — lightweight classification

## Cortex Agent Syntax
```sql
CREATE OR REPLACE AGENT agent_name
  WITH PROFILE = '{"display_name":"..."}'
  FROM SPECIFICATION $$
  spec:
    ...
  $$;
```

## Stage Encryption
PDF_STAGE uses `ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')` — REQUIRED for AI_PARSE_DOCUMENT compatibility. Never change to SNOWFLAKE_FULL.

## Cost Tracking
Every lever procedure inserts rows with token counts and estimated credits. Use `CORTEX_FUNCTIONS_USAGE_HISTORY` view (columns: START_TIME, END_TIME, FUNCTION_NAME, MODEL_NAME, WAREHOUSE_ID, TOKEN_CREDITS, TOKENS) for system-level telemetry.
