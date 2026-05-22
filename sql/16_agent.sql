-- =============================================================================
-- 16_agent.sql — Cortex Agent over Cortex Search Service
-- Enables natural language Q and A over the legal corpus without re-parsing.
-- =============================================================================
USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

-- Why this matters: Once documents are chunked and indexed, an agent provides
-- a conversational interface. Users ask legal questions without needing to know
-- which PDF or page contains the answer — dramatic UX improvement + cost savings
-- (search retrieves ~5 chunks vs feeding 200-page PDFs to the LLM).
CREATE OR REPLACE AGENT LEGAL_DOC_AI_AGENT
    WITH PROFILE = '{"display_name": "Legal Doc AI Q and A Agent"}'
    FROM SPECIFICATION $$
models:
  orchestration: claude-4-sonnet

instructions:
  system: |
    You are a legal research assistant for the US Regulatory & Regulatory Committee.
    Answer questions about the customer governance, Regulatory rules, compliance regulations,
    subject safety policies, and arbitration decisions.

    Always cite the source document name (doc_name) and approximate page/chunk number
    (page_no) from search results. If the search results don't contain relevant
    information, say so clearly rather than guessing.

    Be precise and factual. Quote relevant text when it helps the user understand
    the answer.

tools:
  - tool_spec:
      type: cortex_search
      name: legal_search
      description: "Searches legal documents for relevant passages"

tool_resources:
  legal_search:
    name: "SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH"
    max_results: 5
    filter_columns:
      - doc_name
$$;
