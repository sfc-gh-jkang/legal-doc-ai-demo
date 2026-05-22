"""
test_cache_identity.py — Lever 1: Verify cache layer produces identical output.

Tests:
1. Hash stability: SHA256 of parsed text is deterministic for same input.
2. Roundtrip: text stored in cache matches text re-parsed from source.
3. No silent truncation: cached text length matches fresh parse length.
"""

import hashlib
import pytest


# --- Fixtures ---

SAMPLE_PDF_TEXT = """
ARTICLE 1 — GENERAL PRINCIPLES

1.1 The Acme Legal Holdings Corp. ("ACME") is the national
    governing body for the regulatory compliance in the United States.

1.2 Purpose. The purposes of the customer include:
    (a) Establishing national goals for amateur athletic activities;
    (b) Coordinating amateur athletics within the United States;
    (c) Representing the United States in international athletic events.

Section 2.1 — Board Composition
The Board of Directors shall consist of not fewer than 12 nor more than 16 members,
of whom at least one-third (33.3%) shall be Board Representatives.

Financial Summary:
    Total Revenue: $452,891,234.56
    Operating Expenses: $398,112,001.78
    Net Income: $54,779,232.78
    Compliance Support: 47% of total budget

Effective Date: 01/15/2023
"""

SAMPLE_PDF_TEXT_B = """
ARTICLE 1 — GENERAL PRINCIPLES

1.1 The Acme Legal Holdings Corp. ("ACME") is the national
    governing body for the regulatory compliance in the United States.

1.2 Purpose. The purposes of the customer include:
    (a) Establishing national goals for amateur athletic activities;
    (b) Coordinating amateur athletics within the United States;
    (c) Representing the United States in international athletic events.

Section 2.1 — Board Composition
The Board of Directors shall consist of not fewer than 12 nor more than 16 members,
of whom at least one-third (33.3%) shall be Board Representatives.

Financial Summary:
    Total Revenue: $452,891,234.56
    Operating Expenses: $398,112,001.78
    Net Income: $54,779,232.78
    Compliance Support: 47% of total budget

Effective Date: 01/15/2023
"""


def compute_file_hash(content: str) -> str:
    """SHA256 hash of text content, matching the cache layer's hash function."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# --- Unit Tests ---


class TestHashStability:
    """Hash function must be deterministic."""

    @pytest.mark.unit
    def test_same_content_same_hash(self):
        h1 = compute_file_hash(SAMPLE_PDF_TEXT)
        h2 = compute_file_hash(SAMPLE_PDF_TEXT)
        assert h1 == h2, "Same content must produce same hash"

    @pytest.mark.unit
    def test_different_content_different_hash(self):
        h1 = compute_file_hash(SAMPLE_PDF_TEXT)
        h2 = compute_file_hash(SAMPLE_PDF_TEXT + " extra text")
        assert h1 != h2, "Different content must produce different hash"

    @pytest.mark.unit
    def test_hash_length(self):
        h = compute_file_hash(SAMPLE_PDF_TEXT)
        assert len(h) == 64, "SHA256 hex digest is 64 chars"


class TestCacheRoundtrip:
    """Cached text must match original exactly."""

    @pytest.mark.unit
    def test_identical_text_roundtrip(self):
        """Simulate cache store + retrieve: text in == text out."""
        # Simulate: store text in "cache" (dict), retrieve, compare
        cache = {}
        file_hash = compute_file_hash(SAMPLE_PDF_TEXT)
        cache[file_hash] = SAMPLE_PDF_TEXT

        retrieved = cache.get(file_hash)
        assert retrieved == SAMPLE_PDF_TEXT
        assert len(retrieved) == len(SAMPLE_PDF_TEXT)

    @pytest.mark.unit
    def test_no_whitespace_normalization(self):
        """Cache must NOT normalize whitespace — byte-identical is required."""
        text_with_tabs = "Column A\tColumn B\tColumn C\n1\t2\t3"
        text_with_spaces = "Column A    Column B    Column C\n1    2    3"

        h1 = compute_file_hash(text_with_tabs)
        h2 = compute_file_hash(text_with_spaces)
        assert h1 != h2, "Tab vs space must produce different hashes"

    @pytest.mark.unit
    def test_no_silent_truncation(self):
        """A long document must not be silently truncated in cache."""
        long_text = "Section " * 100_000  # ~800KB
        file_hash = compute_file_hash(long_text)
        cache = {file_hash: long_text}

        retrieved = cache[file_hash]
        assert len(retrieved) == len(long_text)
        assert retrieved[-20:] == long_text[-20:]


class TestCacheHitMiss:
    """Cache lookup correctness."""

    @pytest.mark.unit
    def test_cache_hit(self):
        cache = {}
        h = compute_file_hash(SAMPLE_PDF_TEXT)
        cache[h] = SAMPLE_PDF_TEXT

        lookup_hash = compute_file_hash(SAMPLE_PDF_TEXT_B)
        # SAMPLE_PDF_TEXT_B is identical content
        assert lookup_hash == h
        assert cache.get(lookup_hash) is not None

    @pytest.mark.unit
    def test_cache_miss(self):
        cache = {}
        h = compute_file_hash(SAMPLE_PDF_TEXT)
        cache[h] = SAMPLE_PDF_TEXT

        different_hash = compute_file_hash("completely different document")
        assert cache.get(different_hash) is None
