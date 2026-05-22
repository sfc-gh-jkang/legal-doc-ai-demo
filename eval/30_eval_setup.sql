-- =============================================================================
-- 30_eval_setup.sql — Eval result tables for the Legal Doc AI cost-quality framework
-- Schema: SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO
-- =============================================================================

CREATE TABLE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RUNS (
    RUN_ID       STRING        NOT NULL,
    LEVER        STRING        NOT NULL,  -- 'cache'|'routing'|'model'|'structured'|'retrieval'
    RUN_AT       TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    NOTES        VARCHAR
);

CREATE TABLE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_PER_DOC (
    RUN_ID              STRING  NOT NULL,
    LEVER               STRING  NOT NULL,
    FILENAME            STRING  NOT NULL,
    SIMILARITY_TO_GOLD  FLOAT,
    JUDGE_SCORE         NUMBER(3,1),
    AGREEMENT_WITH_GOLD BOOLEAN,
    TOKENS_IN           NUMBER,
    TOKENS_OUT          NUMBER,
    CREDITS_ESTIMATED   FLOAT,
    NUMERIC_FIDELITY    FLOAT,
    NOTES               VARCHAR
);

CREATE TABLE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS (
    QA_ID        STRING  NOT NULL,
    QUESTION     VARCHAR NOT NULL,
    GOLD_ANSWER  VARCHAR NOT NULL,
    SOURCE_DOC   STRING  NOT NULL,
    SOURCE_PAGE  NUMBER,
    QUESTION_TYPE STRING,
    CONFIDENCE   STRING  DEFAULT 'needs_spotcheck'
);

CREATE TABLE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_RESULTS (
    QA_ID              STRING  NOT NULL,
    RUN_ID             STRING  NOT NULL,
    RETRIEVAL_METHOD   STRING,           -- 'cortex_search'|'full_doc_stuff'|'hybrid'
    RETRIEVED_CHUNKS   ARRAY,
    MODEL              STRING,
    GENERATED_ANSWER   VARCHAR,
    SIMILARITY_TO_GOLD FLOAT,
    RECALL_AT_5        FLOAT,
    MRR                FLOAT
);

CREATE TABLE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_RETRY_RATES (
    RUN_ID             STRING  NOT NULL,
    MODE               STRING  NOT NULL,  -- 'free_text'|'structured'
    RETRY_COUNT_TOTAL  NUMBER,
    TOTAL_ATTEMPTS     NUMBER,
    RETRY_RATE_PCT     FLOAT
);
