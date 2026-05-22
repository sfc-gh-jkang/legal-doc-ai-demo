-- =============================================================================
-- 09_grounded_qa_pairs.sql — Grounded Q&A evaluation pairs from corpus
-- Schema: SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO
-- Generates 30 Q&A pairs (6 per document) using AI_COMPLETE on PARSED_CACHE
-- =============================================================================

-- Ensure EVAL_QA_PAIRS has required columns (already created in 30_eval_setup.sql)
-- Columns: QA_ID, QUESTION, GOLD_ANSWER, SOURCE_DOC, SOURCE_PAGE, QUESTION_TYPE, CONFIDENCE

-- Regenerate grounded Q&A pairs from all parsed documents
TRUNCATE TABLE SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS;

INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS
    (QA_ID, QUESTION, GOLD_ANSWER, SOURCE_DOC, SOURCE_PAGE, QUESTION_TYPE, CONFIDENCE)
WITH doc_qa AS (
    SELECT
        PC.FILENAME,
        SNOWFLAKE.CORTEX.AI_COMPLETE(
            'claude-4-sonnet',
            'You are helping create evaluation data for a legal document AI system. Read this legal document excerpt and generate exactly 6 questions a the customer compliance officer might ask, with precise answers grounded in the text. Cover different question types: factual, definitional, procedural, numerical, cross-reference, and interpretive.

Return ONLY a JSON array (no markdown, no code fences): [{"question": "...", "answer": "...", "source_page": <number or 1 if unknown>, "question_type": "<factual|definitional|procedural|numerical|cross_reference|interpretive>", "confidence": "<high|medium>"}]

Document (' || PC.FILENAME || '):
' || LEFT(PC.PARSED_TEXT, 8000)
        ) AS RAW_RESPONSE
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE PC
),
parsed_qa AS (
    SELECT
        DQ.FILENAME,
        REGEXP_REPLACE(DQ.RAW_RESPONSE, '```json|```', '') AS CLEAN_JSON
    FROM doc_qa DQ
),
flattened AS (
    SELECT
        PQ.FILENAME,
        F.INDEX AS IDX,
        F.VALUE:question::VARCHAR AS QUESTION,
        F.VALUE:answer::VARCHAR AS ANSWER,
        F.VALUE:source_page::NUMBER AS SOURCE_PAGE,
        F.VALUE:question_type::VARCHAR AS QUESTION_TYPE,
        F.VALUE:confidence::VARCHAR AS CONFIDENCE
    FROM parsed_qa PQ,
    LATERAL FLATTEN(INPUT => TRY_PARSE_JSON(TRIM(PQ.CLEAN_JSON))) F
)
SELECT
    MD5(F.FILENAME || '_' || F.IDX::VARCHAR) AS QA_ID,
    F.QUESTION,
    F.ANSWER,
    F.FILENAME AS SOURCE_DOC,
    COALESCE(F.SOURCE_PAGE, 1) AS SOURCE_PAGE,
    F.QUESTION_TYPE,
    COALESCE(F.CONFIDENCE, 'needs_spotcheck') AS CONFIDENCE
FROM flattened F
WHERE F.QUESTION IS NOT NULL;

-- Verify
SELECT COUNT(*) AS QA_PAIR_COUNT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS;
SELECT * FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS LIMIT 5;
