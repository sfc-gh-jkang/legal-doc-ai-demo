USE DATABASE SNOWFLAKE_EXAMPLE;
USE SCHEMA LEGAL_DOC_AI_DEMO;
USE WAREHOUSE SFE_LEGAL_DOC_AI_WH;

TRUNCATE TABLE SCORER_AB;

-- claude-haiku-4-5
INSERT INTO SCORER_AB (FILENAME, SCORER_MODEL, SCORING_RESULT, AGREEMENT_WITH_GOLD, 
                       SIMILARITY_TO_GOLD, SCORE_TOKENS, SCORE_CREDITS_EST)
WITH p AS (
    SELECT FILENAME, SCORING_RESULT_JSON AS GOLD,
        'Compare these two PDF extractions and determine which is higher quality. '
        || 'Consider: text completeness, table/list formatting, readability.\n\n'
        || '--- OCR ---\n' || LEFT(OCR_TEXT, 3000) || '\n\n'
        || '--- LAYOUT ---\n' || LEFT(LAYOUT_TEXT, 3000) || '\n\n'
        || 'Return JSON: {"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}'
        AS PROMPT_TEXT FROM BASELINE_RESULTS
), r AS (
    SELECT FILENAME, GOLD, PROMPT_TEXT, AI_COMPLETE('claude-haiku-4-5', PROMPT_TEXT) AS RESP FROM p
)
SELECT FILENAME, 'claude-haiku-4-5', RESP,
    (REGEXP_SUBSTR(RESP, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1) = REGEXP_SUBSTR(GOLD, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1)),
    AI_SIMILARITY(RESP, GOLD),
    CAST((LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4 AS NUMBER),
    (LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4.0 * 0.3 / 1000000.0 FROM r;

-- claude-sonnet-4-6
INSERT INTO SCORER_AB (FILENAME, SCORER_MODEL, SCORING_RESULT, AGREEMENT_WITH_GOLD, 
                       SIMILARITY_TO_GOLD, SCORE_TOKENS, SCORE_CREDITS_EST)
WITH p AS (
    SELECT FILENAME, SCORING_RESULT_JSON AS GOLD,
        'Compare these two PDF extractions and determine which is higher quality. '
        || 'Consider: text completeness, table/list formatting, readability.\n\n'
        || '--- OCR ---\n' || LEFT(OCR_TEXT, 3000) || '\n\n'
        || '--- LAYOUT ---\n' || LEFT(LAYOUT_TEXT, 3000) || '\n\n'
        || 'Return JSON: {"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}'
        AS PROMPT_TEXT FROM BASELINE_RESULTS
), r AS (
    SELECT FILENAME, GOLD, PROMPT_TEXT, AI_COMPLETE('claude-sonnet-4-6', PROMPT_TEXT) AS RESP FROM p
)
SELECT FILENAME, 'claude-sonnet-4-6', RESP,
    (REGEXP_SUBSTR(RESP, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1) = REGEXP_SUBSTR(GOLD, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1)),
    AI_SIMILARITY(RESP, GOLD),
    CAST((LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4 AS NUMBER),
    (LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4.0 * 3.0 / 1000000.0 FROM r;

-- mistral-large2
INSERT INTO SCORER_AB (FILENAME, SCORER_MODEL, SCORING_RESULT, AGREEMENT_WITH_GOLD, 
                       SIMILARITY_TO_GOLD, SCORE_TOKENS, SCORE_CREDITS_EST)
WITH p AS (
    SELECT FILENAME, SCORING_RESULT_JSON AS GOLD,
        'Compare these two PDF extractions and determine which is higher quality. '
        || 'Consider: text completeness, table/list formatting, readability.\n\n'
        || '--- OCR ---\n' || LEFT(OCR_TEXT, 3000) || '\n\n'
        || '--- LAYOUT ---\n' || LEFT(LAYOUT_TEXT, 3000) || '\n\n'
        || 'Return JSON: {"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}'
        AS PROMPT_TEXT FROM BASELINE_RESULTS
), r AS (
    SELECT FILENAME, GOLD, PROMPT_TEXT, AI_COMPLETE('mistral-large2', PROMPT_TEXT) AS RESP FROM p
)
SELECT FILENAME, 'mistral-large2', RESP,
    (REGEXP_SUBSTR(RESP, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1) = REGEXP_SUBSTR(GOLD, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1)),
    AI_SIMILARITY(RESP, GOLD),
    CAST((LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4 AS NUMBER),
    (LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4.0 * 1.95 / 1000000.0 FROM r;

-- llama3.3-70b
INSERT INTO SCORER_AB (FILENAME, SCORER_MODEL, SCORING_RESULT, AGREEMENT_WITH_GOLD, 
                       SIMILARITY_TO_GOLD, SCORE_TOKENS, SCORE_CREDITS_EST)
WITH p AS (
    SELECT FILENAME, SCORING_RESULT_JSON AS GOLD,
        'Compare these two PDF extractions and determine which is higher quality. '
        || 'Consider: text completeness, table/list formatting, readability.\n\n'
        || '--- OCR ---\n' || LEFT(OCR_TEXT, 3000) || '\n\n'
        || '--- LAYOUT ---\n' || LEFT(LAYOUT_TEXT, 3000) || '\n\n'
        || 'Return JSON: {"best_mode": "OCR" or "LAYOUT", "confidence": 0.0-1.0, "reasoning": "..."}'
        AS PROMPT_TEXT FROM BASELINE_RESULTS
), r AS (
    SELECT FILENAME, GOLD, PROMPT_TEXT, AI_COMPLETE('llama3.3-70b', PROMPT_TEXT) AS RESP FROM p
)
SELECT FILENAME, 'llama3.3-70b', RESP,
    (REGEXP_SUBSTR(RESP, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1) = REGEXP_SUBSTR(GOLD, '"best_mode"\\s*:\\s*"([A-Z]+)"', 1, 1, 'e', 1)),
    AI_SIMILARITY(RESP, GOLD),
    CAST((LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4 AS NUMBER),
    (LENGTH(PROMPT_TEXT) + LENGTH(RESP)) / 4.0 * 1.21 / 1000000.0 FROM r;

-- claude-4-sonnet (gold) — just copy from BASELINE_RESULTS
INSERT INTO SCORER_AB (FILENAME, SCORER_MODEL, SCORING_RESULT, AGREEMENT_WITH_GOLD, 
                       SIMILARITY_TO_GOLD, SCORE_TOKENS, SCORE_CREDITS_EST)
SELECT FILENAME, 'claude-4-sonnet', SCORING_RESULT_JSON, TRUE, 1.0, SCORE_TOKENS, SCORE_CREDITS_EST
FROM BASELINE_RESULTS;

SELECT SCORER_MODEL, COUNT(*) AS DOCS,
       ROUND(AVG(CASE WHEN AGREEMENT_WITH_GOLD THEN 1.0 ELSE 0.0 END)*100, 1) AS AGREE_PCT,
       ROUND(AVG(SIMILARITY_TO_GOLD), 4) AS MEAN_SIM,
       ROUND(SUM(SCORE_CREDITS_EST), 6) AS TOTAL_CREDITS
FROM SCORER_AB GROUP BY SCORER_MODEL ORDER BY TOTAL_CREDITS;
