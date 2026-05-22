"""
test_routing_oracle.py — Lever 2: Validate smart routing picks the right mode.

The smart router classifies PDFs as digital (→ LAYOUT) or scanned (→ OCR) based on
heuristics (embedded text layer presence, image-to-text ratio, font info).
This test uses fixture documents with known characteristics to verify routing logic.
"""

import pytest


# --- Routing Logic (mirrors sql/12_smart_routing.sql heuristics) ---


def classify_document(
    has_embedded_text: bool,
    text_char_count: int,
    page_count: int,
    has_font_info: bool,
    image_area_ratio: float,
) -> str:
    """
    Classify a PDF for routing: 'LAYOUT' for digital-native, 'OCR' for scanned.

    Heuristics:
    1. If no embedded text layer → definitely scanned → OCR
    2. If embedded text but very low char density → likely image-heavy → OCR
    3. If has font info and reasonable text density → digital → LAYOUT
    4. If image area dominates (>80% of page) → likely scanned → OCR
    """
    # No text layer at all → scanned
    if not has_embedded_text:
        return "OCR"

    # Very sparse text (< 100 chars per page on average) → likely OCR-needed
    chars_per_page = text_char_count / max(page_count, 1)
    if chars_per_page < 100:
        return "OCR"

    # Image dominates the page → scanned document
    if image_area_ratio > 0.80:
        return "OCR"

    # Has font info + decent text density → digital native
    if has_font_info and chars_per_page >= 500:
        return "LAYOUT"

    # Middle ground: has text but unclear → default to LAYOUT (cheaper)
    if has_embedded_text and chars_per_page >= 100:
        return "LAYOUT"

    return "OCR"


def compute_routing_confidence(
    has_embedded_text: bool,
    text_char_count: int,
    page_count: int,
    has_font_info: bool,
    image_area_ratio: float,
) -> float:
    """Confidence score for routing decision (0.0 - 1.0)."""
    score = 0.5  # baseline

    chars_per_page = text_char_count / max(page_count, 1)

    # Strong signals boost confidence
    if not has_embedded_text:
        score = 0.95  # very clear: no text layer = scanned
    elif has_font_info and chars_per_page > 1000:
        score = 0.92  # very clear: rich digital doc
    elif image_area_ratio > 0.90:
        score = 0.88  # clear: image-dominated
    elif chars_per_page < 50:
        score = 0.85  # clear: almost no text
    elif 100 <= chars_per_page < 500:
        score = 0.65  # ambiguous middle ground
    else:
        score = 0.80

    return round(score, 2)


# --- Test Fixtures ---

DIGITAL_DOCS = [
    {
        "name": "Corporate Bylaws (modern digital PDF)",
        "has_embedded_text": True,
        "text_char_count": 120_000,
        "page_count": 45,
        "has_font_info": True,
        "image_area_ratio": 0.05,
        "expected_mode": "LAYOUT",
    },
    {
        "name": "Regulatory Charter (born-digital)",
        "has_embedded_text": True,
        "text_char_count": 200_000,
        "page_count": 110,
        "has_font_info": True,
        "image_area_ratio": 0.02,
        "expected_mode": "LAYOUT",
    },
    {
        "name": "Compliance Code (complex with tables)",
        "has_embedded_text": True,
        "text_char_count": 180_000,
        "page_count": 140,
        "has_font_info": True,
        "image_area_ratio": 0.10,
        "expected_mode": "LAYOUT",
    },
]

SCANNED_DOCS = [
    {
        "name": "Old CAS ruling (scanned, no text layer)",
        "has_embedded_text": False,
        "text_char_count": 0,
        "page_count": 12,
        "has_font_info": False,
        "image_area_ratio": 0.95,
        "expected_mode": "OCR",
    },
    {
        "name": "Handwritten arbitration notes",
        "has_embedded_text": False,
        "text_char_count": 0,
        "page_count": 3,
        "has_font_info": False,
        "image_area_ratio": 0.98,
        "expected_mode": "OCR",
    },
    {
        "name": "Scanned contract with stamps",
        "has_embedded_text": True,
        "text_char_count": 150,  # OCR artifact: tiny amount of garbage text
        "page_count": 8,
        "has_font_info": False,
        "image_area_ratio": 0.92,
        "expected_mode": "OCR",
    },
]

EDGE_CASES = [
    {
        "name": "Mixed doc: some pages digital, some scanned",
        "has_embedded_text": True,
        "text_char_count": 5_000,
        "page_count": 20,
        "has_font_info": True,
        "image_area_ratio": 0.60,
        "expected_mode": "LAYOUT",  # has enough text → LAYOUT
    },
    {
        "name": "Image-heavy presentation export",
        "has_embedded_text": True,
        "text_char_count": 2_000,
        "page_count": 30,
        "has_font_info": True,
        "image_area_ratio": 0.85,
        "expected_mode": "OCR",  # image dominates
    },
]


# --- Tests ---


class TestDigitalRouting:
    """Digital-native PDFs must route to LAYOUT."""

    @pytest.mark.unit
    @pytest.mark.parametrize("doc", DIGITAL_DOCS, ids=[d["name"] for d in DIGITAL_DOCS])
    def test_digital_routes_to_layout(self, doc):
        mode = classify_document(
            has_embedded_text=doc["has_embedded_text"],
            text_char_count=doc["text_char_count"],
            page_count=doc["page_count"],
            has_font_info=doc["has_font_info"],
            image_area_ratio=doc["image_area_ratio"],
        )
        assert mode == doc["expected_mode"], (
            f"{doc['name']}: expected {doc['expected_mode']}, got {mode}"
        )


class TestScannedRouting:
    """Scanned PDFs must route to OCR."""

    @pytest.mark.unit
    @pytest.mark.parametrize("doc", SCANNED_DOCS, ids=[d["name"] for d in SCANNED_DOCS])
    def test_scanned_routes_to_ocr(self, doc):
        mode = classify_document(
            has_embedded_text=doc["has_embedded_text"],
            text_char_count=doc["text_char_count"],
            page_count=doc["page_count"],
            has_font_info=doc["has_font_info"],
            image_area_ratio=doc["image_area_ratio"],
        )
        assert mode == doc["expected_mode"], (
            f"{doc['name']}: expected {doc['expected_mode']}, got {mode}"
        )


class TestEdgeCases:
    """Ambiguous documents should route reasonably."""

    @pytest.mark.unit
    @pytest.mark.parametrize("doc", EDGE_CASES, ids=[d["name"] for d in EDGE_CASES])
    def test_edge_case_routing(self, doc):
        mode = classify_document(
            has_embedded_text=doc["has_embedded_text"],
            text_char_count=doc["text_char_count"],
            page_count=doc["page_count"],
            has_font_info=doc["has_font_info"],
            image_area_ratio=doc["image_area_ratio"],
        )
        assert mode == doc["expected_mode"], (
            f"{doc['name']}: expected {doc['expected_mode']}, got {mode}"
        )


class TestConfidence:
    """Confidence must be higher for clear cases, lower for ambiguous."""

    @pytest.mark.unit
    def test_clear_scanned_high_confidence(self):
        conf = compute_routing_confidence(
            has_embedded_text=False,
            text_char_count=0,
            page_count=10,
            has_font_info=False,
            image_area_ratio=0.95,
        )
        assert conf >= 0.90

    @pytest.mark.unit
    def test_clear_digital_high_confidence(self):
        conf = compute_routing_confidence(
            has_embedded_text=True,
            text_char_count=100_000,
            page_count=50,
            has_font_info=True,
            image_area_ratio=0.05,
        )
        assert conf >= 0.85

    @pytest.mark.unit
    def test_ambiguous_lower_confidence(self):
        conf = compute_routing_confidence(
            has_embedded_text=True,
            text_char_count=3_000,
            page_count=20,
            has_font_info=True,
            image_area_ratio=0.55,
        )
        assert conf < 0.80, f"Ambiguous case should have lower confidence, got {conf}"

    @pytest.mark.unit
    def test_confidence_range(self):
        """All confidence values must be 0.0 - 1.0."""
        for doc in DIGITAL_DOCS + SCANNED_DOCS + EDGE_CASES:
            conf = compute_routing_confidence(
                has_embedded_text=doc["has_embedded_text"],
                text_char_count=doc["text_char_count"],
                page_count=doc["page_count"],
                has_font_info=doc["has_font_info"],
                image_area_ratio=doc["image_area_ratio"],
            )
            assert 0.0 <= conf <= 1.0, f"{doc['name']}: confidence {conf} out of range"
