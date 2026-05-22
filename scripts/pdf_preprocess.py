"""pdf_preprocess.py — Drop blank pages, compress images, reduce PDF size before AI_PARSE_DOCUMENT.

Usage:
    uv run python scripts/pdf_preprocess.py --src-stage @PDF_STAGE --dst-stage @PDF_STAGE_PROCESSED

Requires: pypdf, Pillow (declared in scripts/pyproject.toml)
"""

import argparse
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("ERROR: pypdf not installed. Run: uv add pypdf Pillow --project scripts/")

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: Pillow not installed. Run: uv add pypdf Pillow --project scripts/")


CONNECTION = "aws_spcs"
JPEG_QUALITY = 60
MIN_TEXT_FOR_PAGE = 50  # chars below which page is considered "blank" (if also no images)


def snow_sql(query: str) -> str:
    """Execute SQL via snow CLI and return stdout."""
    result = subprocess.run(
        ["snow", "sql", "-c", CONNECTION, "-q", query, "--format", "json"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"SQL ERROR: {result.stderr}", file=sys.stderr)
        return "[]"
    return result.stdout


def ensure_dst_stage(stage_name: str):
    """Create destination stage if not exists."""
    # Strip leading @ if present
    clean_name = stage_name.lstrip("@")
    snow_sql(f"CREATE STAGE IF NOT EXISTS SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.{clean_name} ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');")
    print(f"  Stage {clean_name} ready")


def list_stage_files(stage_path: str) -> list[dict]:
    """List PDF files on a Snowflake stage."""
    raw = snow_sql(f"LIST {stage_path} PATTERN='.*\\.pdf';")
    try:
        rows = json.loads(raw)
        return [r for r in rows if r.get("name", "").endswith(".pdf")]
    except json.JSONDecodeError:
        return []


def download_from_stage(stage_path: str, filename: str, dest_dir: Path) -> Path:
    """Download a file from stage to local path."""
    local_path = dest_dir / filename
    subprocess.run(
        ["snow", "stage", "copy", f"{stage_path}/{filename}", str(dest_dir), "-c", CONNECTION],
        capture_output=True, text=True, timeout=120,
    )
    return local_path


def upload_to_stage(local_path: Path, stage_path: str):
    """Upload a local file to Snowflake stage."""
    subprocess.run(
        ["snow", "stage", "copy", str(local_path), stage_path, "-c", CONNECTION, "--overwrite"],
        capture_output=True, text=True, timeout=120,
    )


def compress_image(img: Image.Image) -> bytes:
    """Compress a PIL Image to JPEG with reduced quality."""
    buf = io.BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def is_blank_page(page) -> bool:
    """Heuristic: page is blank if text < threshold AND no images."""
    text = page.extract_text() or ""
    has_images = len(page.images) > 0 if hasattr(page, "images") else False
    return len(text.strip()) < MIN_TEXT_FOR_PAGE and not has_images


def process_pdf(input_path: Path, output_path: Path) -> dict:
    """Process a PDF: drop blank pages, compress images. Returns stats."""
    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    original_pages = len(reader.pages)
    kept_pages = 0
    blank_dropped = 0

    for page in reader.pages:
        if is_blank_page(page):
            blank_dropped += 1
            continue
        writer.add_page(page)
        kept_pages += 1

    # If all pages were blank, keep at least the first page
    if kept_pages == 0 and original_pages > 0:
        writer.add_page(reader.pages[0])
        kept_pages = 1
        blank_dropped = original_pages - 1

    # Write output
    with open(output_path, "wb") as f:
        writer.write(f)

    original_size = input_path.stat().st_size
    processed_size = output_path.stat().st_size

    return {
        "original_pages": original_pages,
        "kept_pages": kept_pages,
        "blank_dropped": blank_dropped,
        "original_bytes": original_size,
        "processed_bytes": processed_size,
        "size_delta_pct": round((1 - processed_size / max(original_size, 1)) * 100, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Preprocess PDFs: drop blank pages, compress")
    parser.add_argument("--src-stage", default="@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PDF_STAGE")
    parser.add_argument("--dst-stage", default="@SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PDF_STAGE_PROCESSED")
    args = parser.parse_args()

    print("PDF Preprocessor")
    print(f"  Source: {args.src_stage}")
    print(f"  Dest:   {args.dst_stage}")
    print()

    # Ensure destination stage exists
    ensure_dst_stage(args.dst_stage.lstrip("@").split(".")[-1])

    # List source files
    files = list_stage_files(args.src_stage)
    if not files:
        print("No PDF files found on source stage.")
        return

    print(f"Found {len(files)} PDF(s) to process\n")

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        src_dir = tmp / "src"
        dst_dir = tmp / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()

        for file_info in files:
            # Extract filename from stage path (format: stage_name/filename.pdf)
            full_name = file_info.get("name", "")
            filename = full_name.split("/")[-1]
            if not filename:
                continue

            print(f"  Processing: {filename}")

            # Download
            local_src = download_from_stage(args.src_stage, filename, src_dir)
            if not local_src.exists():
                print("    SKIP: download failed")
                continue

            # Process
            local_dst = dst_dir / filename
            try:
                stats = process_pdf(local_src, local_dst)
            except Exception as e:
                print(f"    ERROR: {e}")
                # On error, just copy the original
                import shutil
                shutil.copy2(local_src, local_dst)
                stats = {
                    "original_pages": 0, "kept_pages": 0, "blank_dropped": 0,
                    "original_bytes": local_src.stat().st_size,
                    "processed_bytes": local_dst.stat().st_size,
                    "size_delta_pct": 0,
                }

            stats["filename"] = filename
            results.append(stats)
            print(f"    Pages: {stats['original_pages']} -> {stats['kept_pages']} (dropped {stats['blank_dropped']})")
            print(f"    Size:  {stats['original_bytes']:,} -> {stats['processed_bytes']:,} ({stats['size_delta_pct']}% reduction)")

            # Upload processed file
            upload_to_stage(local_dst, args.dst_stage)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_orig_pages = sum(r["original_pages"] for r in results)
    total_kept_pages = sum(r["kept_pages"] for r in results)
    total_orig_bytes = sum(r["original_bytes"] for r in results)
    total_proc_bytes = sum(r["processed_bytes"] for r in results)
    print(f"  Files processed: {len(results)}")
    print(f"  Total pages:     {total_orig_pages} -> {total_kept_pages} ({total_orig_pages - total_kept_pages} dropped)")
    print(f"  Total size:      {total_orig_bytes:,} -> {total_proc_bytes:,} bytes")
    print(f"  Overall savings: {round((1 - total_proc_bytes / max(total_orig_bytes, 1)) * 100, 1)}%")

    # Insert results into Snowflake table
    for r in results:
        credits_saved = r["blank_dropped"] * 0.0035  # est credits saved per dropped page
        snow_sql(
            f"INSERT INTO SNOWFLAKE_EXAMPLE.LEGAL_DOC_AI_DEMO.PREPROCESS_LOG "
            f"(FILE_NAME, ORIGINAL_PAGES, KEPT_PAGES, BLANK_DROPPED, ORIGINAL_BYTES, PROCESSED_BYTES, EST_CREDITS_SAVED) "
            f"VALUES ('{r['filename']}', {r['original_pages']}, {r['kept_pages']}, {r['blank_dropped']}, "
            f"{r['original_bytes']}, {r['processed_bytes']}, {credits_saved})"
        )


if __name__ == "__main__":
    main()
