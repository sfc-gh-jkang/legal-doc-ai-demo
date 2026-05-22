USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

SET retrieval_run_id = (SELECT MAX(RUN_ID) FROM EVAL_RUNS WHERE LEVER = 'retrieval');

CREATE OR REPLACE TEMPORARY TABLE _SEARCH_RESULTS AS
SELECT 'qa_001' AS QA_ID, PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
    'SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH',
    '{"query": "What auditing standards must registered public accounting firms follow under Sarbanes-Oxley Section 103?", "columns": ["chunk_text", "doc_name"], "limit": 5}'
)) AS SEARCH_JSON
UNION ALL SELECT 'qa_002', PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
    'SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH',
    '{"query": "What is the primary purpose of the Health Insurance Portability and Accountability Act?", "columns": ["chunk_text", "doc_name"], "limit": 5}'))
UNION ALL SELECT 'qa_003', PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
    'SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH',
    '{"query": "What did the Emergency Economic Stabilization Act of 2008 establish?", "columns": ["chunk_text", "doc_name"], "limit": 5}'))
UNION ALL SELECT 'qa_004', PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
    'SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH',
    '{"query": "What does the Dodd-Frank Wall Street Reform Act establish for consumer financial protection?", "columns": ["chunk_text", "doc_name"], "limit": 5}'))
UNION ALL SELECT 'qa_005', PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
    'SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.LEGAL_DOC_AI_SEARCH',
    '{"query": "What does CFR Title 16 Part 1 govern?", "columns": ["chunk_text", "doc_name"], "limit": 5}'));

-- Compute MRR via flattened join (avoid correlated subquery)
CREATE OR REPLACE TEMPORARY TABLE _RETRIEVAL_PREP AS
WITH chunks_per_qa AS (
    SELECT
        SR.QA_ID,
        SR.SEARCH_JSON:results AS CHUNKS,
        ARRAY_TO_STRING(
            ARRAY_AGG(F.VALUE:chunk_text::VARCHAR) WITHIN GROUP (ORDER BY F.INDEX),
            '\n---\n'
        ) AS CONTEXT_TEXT
    FROM _SEARCH_RESULTS SR, LATERAL FLATTEN(input => SR.SEARCH_JSON:results) F
    GROUP BY SR.QA_ID, SR.SEARCH_JSON
),
matches AS (
    SELECT
        SR.QA_ID, QP.SOURCE_DOC,
        MIN(CASE WHEN F.VALUE:doc_name::VARCHAR = QP.SOURCE_DOC THEN F.INDEX END) AS FIRST_MATCH_IDX,
        SUM(CASE WHEN F.VALUE:doc_name::VARCHAR = QP.SOURCE_DOC THEN 1 ELSE 0 END) AS MATCH_COUNT
    FROM _SEARCH_RESULTS SR
    JOIN EVAL_QA_PAIRS QP ON QP.QA_ID = SR.QA_ID,
    LATERAL FLATTEN(input => SR.SEARCH_JSON:results) F
    GROUP BY SR.QA_ID, QP.SOURCE_DOC
)
SELECT
    QP.QA_ID, QP.QUESTION, QP.GOLD_ANSWER, QP.SOURCE_DOC,
    C.CHUNKS, C.CONTEXT_TEXT,
    CASE WHEN M.MATCH_COUNT > 0 THEN 1.0 ELSE 0.0 END AS RECALL,
    CASE WHEN M.FIRST_MATCH_IDX IS NOT NULL THEN 1.0 / (M.FIRST_MATCH_IDX + 1) ELSE 0.0 END AS MRR
FROM EVAL_QA_PAIRS QP
JOIN chunks_per_qa C ON C.QA_ID = QP.QA_ID
JOIN matches M ON M.QA_ID = QP.QA_ID;

-- Generate retrieval answers
INSERT INTO EVAL_QA_RESULTS (QA_ID, RUN_ID, RETRIEVAL_METHOD, RETRIEVED_CHUNKS,
                              MODEL, GENERATED_ANSWER, SIMILARITY_TO_GOLD, RECALL_AT_5, MRR)
WITH ans AS (
    SELECT QA_ID, GOLD_ANSWER, CHUNKS, RECALL, MRR,
        AI_COMPLETE('claude-haiku-4-5',
            'Answer the question using ONLY the provided context. Be concise.\n\nContext:\n' ||
            LEFT(CONTEXT_TEXT, 6000) || '\n\nQuestion: ' || QUESTION
        ) AS ANSWER
    FROM _RETRIEVAL_PREP
)
SELECT QA_ID, $retrieval_run_id, 'cortex_search', CHUNKS, 'claude-haiku-4-5',
    ANSWER, AI_SIMILARITY(ANSWER, GOLD_ANSWER), RECALL, MRR
FROM ans;

INSERT INTO EVAL_QA_RESULTS (QA_ID, RUN_ID, RETRIEVAL_METHOD, MODEL,
                              GENERATED_ANSWER, SIMILARITY_TO_GOLD, RECALL_AT_5, MRR)
WITH full_ans AS (
    SELECT QP.QA_ID, QP.GOLD_ANSWER,
        AI_COMPLETE('claude-4-sonnet',
            'Answer the question using the full document below. Be concise.\n\nDocument:\n' ||
            LEFT(BR.LAYOUT_TEXT, 50000) || '\n\nQuestion: ' || QP.QUESTION
        ) AS ANSWER
    FROM EVAL_QA_PAIRS QP
    JOIN BASELINE_RESULTS BR ON BR.FILENAME = QP.SOURCE_DOC
)
SELECT QA_ID, $retrieval_run_id, 'full_doc_stuff', 'claude-4-sonnet',
    ANSWER, AI_SIMILARITY(ANSWER, GOLD_ANSWER), 1.0, 1.0
FROM full_ans;

SELECT RETRIEVAL_METHOD, COUNT(*) AS N,
    ROUND(AVG(SIMILARITY_TO_GOLD), 4) AS MEAN_SIM,
    ROUND(AVG(RECALL_AT_5), 3) AS MEAN_RECALL,
    ROUND(AVG(MRR), 3) AS MEAN_MRR
FROM EVAL_QA_RESULTS WHERE RUN_ID = $retrieval_run_id GROUP BY 1;

SELECT LEVER_NAME, VERDICT FROM EVAL_SUMMARY_V;
