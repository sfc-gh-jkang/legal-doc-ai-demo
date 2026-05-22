"""Upload local PDFs to @PDF_STAGE in Snowflake.

Uploads all PDF files from data/ directory to the LEGAL_DOC_AI_DEMO.PDF_STAGE,
then refreshes the directory table and lists contents.

Usage:
    cd scripts && uv run upload_pdfs.py

Requires:
    - `snow` CLI configured with connection `aws_spcs`
    - PDFs already downloaded via fetch_corpus.py
"""

import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CONNECTION = "aws_spcs"
STAGE = "@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PDF_STAGE"


def run_snow_sql(sql: str) -> str:
    """Execute SQL via snow CLI and return output."""
    result = subprocess.run(
        ["snow", "sql", "-q", sql, "-c", CONNECTION, "--format", "json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}")
    return result.stdout


def upload_pdfs() -> None:
    pdf_files = sorted(DATA_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {DATA_DIR}")
        print("Run fetch_corpus.py first.")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files to upload.\n")

    succeeded = 0
    for pdf in pdf_files:
        print(f"  PUT {pdf.name} → {STAGE}")
        result = subprocess.run(
            [
                "snow",
                "stage",
                "put",
                str(pdf),
                STAGE,
                "-c",
                CONNECTION,
                "--overwrite",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print("      OK")
            succeeded += 1
        else:
            print(f"      FAILED: {result.stderr.strip()}")

    print(f"\nUploaded {succeeded}/{len(pdf_files)} files.")

    # Refresh directory table
    print("\nRefreshing stage directory...")
    run_snow_sql("ALTER STAGE SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PDF_STAGE REFRESH;")

    # List contents
    print("\nStage contents:")
    output = run_snow_sql("LIST @SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PDF_STAGE;")
    print(output if output else "  (empty or error)")


if __name__ == "__main__":
    print("Uploading PDFs to @PDF_STAGE...\n")
    upload_pdfs()
