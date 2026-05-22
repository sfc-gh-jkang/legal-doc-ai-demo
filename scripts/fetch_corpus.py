"""Fetch public legal PDFs for the Legal Doc AI cost-optimization demo.

Downloads freely-available, non-sports federal regulatory documents to data/corpus_v2/.
All sources are public US government documents (govinfo.gov) — no customer data.

Corpus theme: financial regulation, healthcare, cybersecurity oversight, federal IT
acquisition, consumer protection. Customer-agnostic — works for any enterprise legal
or compliance team's document AI workload.

Usage:
    cd scripts && uv run fetch_corpus.py [--include-v2]
"""

import argparse
import sys
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR_V2 = DATA_DIR / "corpus_v2"

# Public legal corpus: (filename, url, description)
# All from www.govinfo.gov (public domain, US government publications).
# Mix of long Public Laws, CFR parts, and GAO oversight reports for variety in
# parse cost (some short, some long) and document structure (statutes, regs, audits).
CORPUS: list[tuple[str, str, str]] = [
    (
        "plaw_107publ204_sarbanes_oxley.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-107publ204/pdf/PLAW-107publ204.pdf",
        "Sarbanes-Oxley Act of 2002 — public-company financial reporting + auditor independence",
    ),
    (
        "plaw_111publ203_dodd_frank.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-111publ203/pdf/PLAW-111publ203.pdf",
        "Dodd-Frank Wall Street Reform and Consumer Protection Act (2010)",
    ),
    (
        "plaw_104publ191_hipaa.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-104publ191/pdf/PLAW-104publ191.pdf",
        "HIPAA — Health Insurance Portability and Accountability Act (1996)",
    ),
    (
        "plaw_111publ148_aca.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-111publ148/pdf/PLAW-111publ148.pdf",
        "ACA — Patient Protection and Affordable Care Act (2010)",
    ),
    (
        "plaw_110publ343_eesa.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-110publ343/pdf/PLAW-110publ343.pdf",
        "Emergency Economic Stabilization Act of 2008 (TARP authorization)",
    ),
    (
        "plaw_115publ232_ndaa.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-115publ232/pdf/PLAW-115publ232.pdf",
        "National Defense Authorization Act for FY 2019",
    ),
    (
        "plaw_118publ31_ndaa_2024.pdf",
        "https://www.govinfo.gov/content/pkg/PLAW-118publ31/pdf/PLAW-118publ31.pdf",
        "National Defense Authorization Act for FY 2024",
    ),
    (
        "cfr_title12_part1_banking.pdf",
        "https://www.govinfo.gov/content/pkg/CFR-2024-title12-vol1/pdf/CFR-2024-title12-vol1-part1.pdf",
        "CFR Title 12 Part 1 — Banks and Banking — investment securities regulations",
    ),
    (
        "cfr_title16_part1_ftc.pdf",
        "https://www.govinfo.gov/content/pkg/CFR-2024-title16-vol1/pdf/CFR-2024-title16-vol1-part1.pdf",
        "CFR Title 16 Part 1 — FTC general procedures for consumer protection",
    ),
]

# Backwards-compat alias: older code paths refer to CORPUS_V2 separately.
CORPUS_V2: list[tuple[str, str, str]] = CORPUS


def fetch_corpus(include_v2: bool = False) -> None:
    """Fetch the corpus into data/corpus_v2/.

    The include_v2 flag is retained for backwards compatibility; the unified
    corpus list is now the canonical demo set.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR_V2.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Legal-Doc-AI-Demo/1.0 (john.kang@snowflake.com; educational use)"
        )
    }

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    for filename, url, description in CORPUS:
        dest = DATA_DIR_V2 / filename
        if dest.exists():
            print(f"  SKIP {filename} (already exists)")
            succeeded.append(filename)
            continue

        print(f"  FETCH {filename}")
        print(f"        {description}")
        try:
            resp = requests.get(url, headers=headers, timeout=120, allow_redirects=True)
            resp.raise_for_status()
            content = resp.content
            if not content.startswith(b"%PDF-"):
                raise ValueError(
                    f"Response did not start with %PDF- magic bytes "
                    f"(got first 16 bytes: {content[:16]!r})"
                )
            dest.write_bytes(content)
            print(f"        OK ({len(content):,} bytes)")
            succeeded.append(filename)
        except Exception as e:
            print(f"        FAILED: {e}")
            failed.append((filename, str(e)))

    print(f"\n{'=' * 60}")
    print(f"Results: {len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        print("\nFailed downloads (check URLs manually):")
        for fname, err in failed:
            print(f"  - {fname}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-v2",
        action="store_true",
        help="Backwards-compat flag (corpus is now unified). Ignored.",
    )
    args = parser.parse_args()
    fetch_corpus(include_v2=args.include_v2)
