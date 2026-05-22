#!/usr/bin/env python3
"""pypdf_fallback.py — Free pypdf text extraction before expensive AI_PARSE_DOCUMENT.

If pypdf extracts readable text (>1000 chars, >80% ASCII printable), skip AI parsing
and save ~0.0035 credits/page in Cortex AI credits.

Usage:
    uv run python scripts/pypdf_fallback.py --stage @PDF_STAGE
"""
import argparse
import sys
import tempfile
from pathlib import Path

try:
    import pypdf
except ImportError:
    sys.exit("pypdf not installed. Run: uv pip install pypdf")

try:
    import snowflake.connector
except ImportError:
    sys.exit("snowflake-connector-python not installed")


def is_english_readable(text: str, threshold: float = 0.80) -> bool:
    """Check if >threshold of chars are ASCII printable."""
    if not text:
        return False
    printable_count = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
    return (printable_count / len(text)) >= threshold


def extract_with_pypdf(pdf_path: Path) -> tuple[str, int]:
    """Extract text using pypdf. Returns (text, char_count)."""
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
        full_text = "\n".join(text_parts)
        return full_text, len(full_text)
    except Exception as e:
        print(f"  pypdf error: {e}")
        return "", 0


def classify_extraction(text: str, char_count: int) -> str:
    """Determine if pypdf extraction is sufficient or AI parsing needed."""
    if char_count > 1000 and is_english_readable(text):
        return "pypdf-success"
    return "requires-ai-parse"


def get_snowflake_connection():
    """Connect using default connection or env vars."""
    return snowflake.connector.connect(
        connection_name="aws_spcs",
        database="SNOWFLAKE_EXAMPLE",
        schema="LEGAL_DOC_AI_DEMO",
        warehouse="SFE_LEGAL_DOC_AI_WH",
    )


def main():
    parser = argparse.ArgumentParser(description="pypdf fallback extraction")
    parser.add_argument("--stage", default="@PDF_STAGE", help="Stage containing PDFs")
    parser.add_argument("--dry-run", action="store_true", help="Print results without DB write")
    args = parser.parse_args()

    conn = get_snowflake_connection()
    cur = conn.cursor()

    # List files in stage
    cur.execute(f"LIST {args.stage}")
    stage_files = [row[0] for row in cur.fetchall() if row[0].lower().endswith(".pdf")]

    if not stage_files:
        print("No PDF files found in stage.")
        return

    print(f"Found {len(stage_files)} PDF(s) in {args.stage}")
    results = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for stage_path in stage_files:
            file_name = Path(stage_path).name
            print(f"\n  Processing: {file_name}")

            # Download from stage
            local_path = Path(tmpdir) / file_name
            try:
                cur.execute(f"GET {args.stage}/{file_name} 'file://{tmpdir}/'")
            except Exception as e:
                print(f"    GET failed: {e}")
                results.append({
                    "file_name": file_name,
                    "path_used": "requires-ai-parse",
                    "char_count": 0,
                    "est_credits_saved": 0.0,
                })
                continue

            # Try pypdf extraction
            text, char_count = extract_with_pypdf(local_path)
            path_used = classify_extraction(text, char_count)

            # Estimate savings: ~0.0035 credits/page for AI_PARSE_DOCUMENT avoided
            try:
                reader = pypdf.PdfReader(str(local_path))
                page_count = len(reader.pages)
            except Exception:
                page_count = 0

            credits_saved = page_count * 0.0035 if path_used == "pypdf-success" else 0.0

            results.append({
                "file_name": file_name,
                "path_used": path_used,
                "char_count": char_count,
                "est_credits_saved": round(credits_saved, 4),
            })
            print(f"    {path_used}: {char_count} chars, {page_count} pages, ${credits_saved:.4f} saved")

    # Insert results into Snowflake
    if not args.dry_run and results:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS EXTRACTION_PATH_LOG (
                FILE_NAME VARCHAR,
                PATH_USED VARCHAR,
                CHAR_COUNT NUMBER,
                EST_CREDITS_SAVED FLOAT,
                RUN_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """)
        for r in results:
            cur.execute(
                "INSERT INTO EXTRACTION_PATH_LOG (FILE_NAME, PATH_USED, CHAR_COUNT, EST_CREDITS_SAVED) "
                "VALUES (%s, %s, %s, %s)",
                (r["file_name"], r["path_used"], r["char_count"], r["est_credits_saved"]),
            )
        print(f"\nInserted {len(results)} rows into EXTRACTION_PATH_LOG")
    elif args.dry_run:
        print("\n[DRY RUN] Would insert:")
        for r in results:
            print(f"  {r}")

    # Print summary
    success = sum(1 for r in results if r["path_used"] == "pypdf-success")
    ai_needed = sum(1 for r in results if r["path_used"] == "requires-ai-parse")
    total_saved = sum(r["est_credits_saved"] for r in results)
    print(f"\n{'='*60}")
    print(f"Summary: {success} pypdf-success, {ai_needed} requires-ai-parse")
    print(f"Estimated credits saved: {total_saved:.4f}")
    print(f"{'='*60}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
