"""generate_grounded_qa.py — Generate grounded Q&A evaluation pairs from PARSED_CACHE.

Calls AI_COMPLETE to produce 6 question/answer pairs per document,
grounded in actual document text. Populates EVAL_QA_PAIRS table.

Usage:
    uv run python scripts/generate_grounded_qa.py
    
This is equivalent to running eval/09_grounded_qa_pairs.sql but provides
better progress output and error handling.
"""

import json
import subprocess
import sys


CONNECTION = "aws_spcs"
PAIRS_PER_DOC = 6


def snow_sql(query: str, fmt: str = "json") -> str:
    result = subprocess.run(
        ["snow", "sql", "-c", CONNECTION, "-q", query, "--format", fmt],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"SQL ERROR: {result.stderr}", file=sys.stderr)
        return "[]" if fmt == "json" else ""
    return result.stdout


def main():
    print("Generating grounded Q&A pairs from PARSED_CACHE...\n")

    # Check how many docs are in PARSED_CACHE
    raw = snow_sql("SELECT FILENAME FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE;")
    try:
        docs = json.loads(raw)
    except json.JSONDecodeError:
        print("ERROR: Could not query PARSED_CACHE")
        sys.exit(1)

    print(f"Found {len(docs)} documents in PARSED_CACHE")
    print(f"Target: {len(docs) * PAIRS_PER_DOC} Q&A pairs ({PAIRS_PER_DOC} per doc)\n")

    # Truncate existing pairs
    snow_sql("TRUNCATE TABLE SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS;", fmt="csv")
    print("Truncated existing EVAL_QA_PAIRS\n")

    # Generate via SQL (single batch call is more efficient than per-doc)
    print("Running AI_COMPLETE to generate Q&A pairs (this takes ~60s)...")
    result = snow_sql("""
INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS
    (QA_ID, QUESTION, GOLD_ANSWER, SOURCE_DOC, SOURCE_PAGE, QUESTION_TYPE, CONFIDENCE)
WITH doc_qa AS (
    SELECT
        PC.FILENAME,
        SNOWFLAKE.CORTEX.AI_COMPLETE(
            'claude-4-sonnet',
            'You are helping create evaluation data for a legal document AI system. Read this legal document excerpt and generate exactly 6 questions a the customer compliance officer might ask, with precise answers grounded in the text. Cover different question types: factual, definitional, procedural, numerical, cross-reference, and interpretive.

Return ONLY a JSON array (no markdown, no code fences): [{"question": "...", "answer": "...", "source_page": <number or 1>, "question_type": "<factual|definitional|procedural|numerical|cross_reference|interpretive>", "confidence": "<high|medium>"}]

Document (' || PC.FILENAME || '):
' || LEFT(PC.PARSED_TEXT, 8000)
        ) AS RAW_RESPONSE
    FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PARSED_CACHE PC
),
parsed_qa AS (
    SELECT DQ.FILENAME, REGEXP_REPLACE(DQ.RAW_RESPONSE, '```json|```', '') AS CLEAN_JSON
    FROM doc_qa DQ
),
flattened AS (
    SELECT
        PQ.FILENAME, F.INDEX AS IDX,
        F.VALUE:question::VARCHAR AS QUESTION,
        F.VALUE:answer::VARCHAR AS ANSWER,
        F.VALUE:source_page::NUMBER AS SOURCE_PAGE,
        F.VALUE:question_type::VARCHAR AS QUESTION_TYPE,
        F.VALUE:confidence::VARCHAR AS CONFIDENCE
    FROM parsed_qa PQ,
    LATERAL FLATTEN(INPUT => TRY_PARSE_JSON(TRIM(PQ.CLEAN_JSON))) F
)
SELECT
    MD5(F.FILENAME || '_' || F.IDX::VARCHAR),
    F.QUESTION, F.ANSWER, F.FILENAME,
    COALESCE(F.SOURCE_PAGE, 1),
    F.QUESTION_TYPE,
    COALESCE(F.CONFIDENCE, 'needs_spotcheck')
FROM flattened F WHERE F.QUESTION IS NOT NULL;
    """, fmt="csv")
    print(f"  Insert result: {result.strip()}")

    # Verify
    count_raw = snow_sql("SELECT COUNT(*) AS CNT FROM SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.EVAL_QA_PAIRS;")
    try:
        count = json.loads(count_raw)[0]["CNT"]
    except (json.JSONDecodeError, IndexError, KeyError):
        count = "unknown"

    print(f"\nResult: {count} Q&A pairs generated")
    if isinstance(count, int) and count >= 30:
        print("PASS: Target of 30 pairs met")
    else:
        print(f"WARNING: Expected 30, got {count}")


if __name__ == "__main__":
    main()
