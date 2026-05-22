"""
test_structured_schema.py — Lever 4: Validate structured output conforms to expected schema.

The structured scorer uses response_format=TYPE OBJECT(...) to guarantee valid JSON.
This test validates that the JSON schema matches what downstream consumers expect.
"""

import json
import pytest


# --- Schema Definition ---

EXPECTED_SCHEMA = {
    "type": "object",
    "required": ["best_mode", "confidence", "reasoning"],
    "properties": {
        "best_mode": {"type": "string", "enum": ["OCR", "LAYOUT"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "minLength": 10},
    },
}


def validate_scorer_output(output: dict) -> list[str]:
    """
    Validate a scorer output dict against the expected schema.
    Returns list of error messages (empty = valid).
    """
    errors = []

    # Required fields
    for field in EXPECTED_SCHEMA["required"]:
        if field not in output:
            errors.append(f"Missing required field: {field}")

    if "best_mode" in output:
        if output["best_mode"] not in ("OCR", "LAYOUT"):
            errors.append(
                f"best_mode must be 'OCR' or 'LAYOUT', got: {output['best_mode']}"
            )

    if "confidence" in output:
        conf = output["confidence"]
        if not isinstance(conf, (int, float)):
            errors.append(f"confidence must be numeric, got: {type(conf).__name__}")
        elif conf < 0.0 or conf > 1.0:
            errors.append(f"confidence must be 0.0-1.0, got: {conf}")

    if "reasoning" in output:
        reasoning = output["reasoning"]
        if not isinstance(reasoning, str):
            errors.append(f"reasoning must be string, got: {type(reasoning).__name__}")
        elif len(reasoning) < 10:
            errors.append(
                f"reasoning too short (min 10 chars), got: {len(reasoning)} chars"
            )

    return errors


# --- Test Fixtures (simulated model outputs) ---

VALID_OUTPUTS = [
    {
        "best_mode": "OCR",
        "confidence": 0.92,
        "reasoning": "Document appears to be a scanned image with handwritten annotations. OCR mode preserves character-level accuracy better than layout parsing for this document type.",
    },
    {
        "best_mode": "LAYOUT",
        "confidence": 0.87,
        "reasoning": "Digital-native PDF with clear structure, headers, and embedded text layer. Layout mode preserves hierarchical structure and table formatting.",
    },
    {
        "best_mode": "OCR",
        "confidence": 0.51,
        "reasoning": "Mixed document with some scanned pages and some digital. OCR chosen due to marginally better numeric preservation in scanned sections, though confidence is low.",
    },
]

INVALID_OUTPUTS = [
    # Missing best_mode
    (
        {"confidence": 0.9, "reasoning": "Some reasoning text here"},
        ["Missing required field: best_mode"],
    ),
    # Invalid best_mode value
    (
        {"best_mode": "BOTH", "confidence": 0.9, "reasoning": "Some reasoning text"},
        ["best_mode must be 'OCR' or 'LAYOUT', got: BOTH"],
    ),
    # Confidence out of range
    (
        {"best_mode": "OCR", "confidence": 1.5, "reasoning": "Some reasoning text"},
        ["confidence must be 0.0-1.0, got: 1.5"],
    ),
    # Reasoning too short
    (
        {"best_mode": "OCR", "confidence": 0.9, "reasoning": "Short"},
        ["reasoning too short (min 10 chars), got: 5 chars"],
    ),
    # Missing all fields
    (
        {},
        [
            "Missing required field: best_mode",
            "Missing required field: confidence",
            "Missing required field: reasoning",
        ],
    ),
    # Confidence is string (common LLM mistake)
    (
        {
            "best_mode": "OCR",
            "confidence": "high",
            "reasoning": "Some valid reasoning text here",
        },
        ["confidence must be numeric, got: str"],
    ),
]


# --- Unit Tests ---


class TestValidOutputs:
    """All well-formed outputs must pass validation."""

    @pytest.mark.unit
    @pytest.mark.parametrize("output", VALID_OUTPUTS)
    def test_valid_output_passes(self, output):
        errors = validate_scorer_output(output)
        assert errors == [], f"Valid output should pass, got errors: {errors}"

    @pytest.mark.unit
    @pytest.mark.parametrize("output", VALID_OUTPUTS)
    def test_valid_output_json_serializable(self, output):
        """Must be JSON-serializable for storage in Snowflake VARIANT."""
        serialized = json.dumps(output)
        deserialized = json.loads(serialized)
        assert deserialized == output


class TestInvalidOutputs:
    """Malformed outputs must be caught with clear error messages."""

    @pytest.mark.unit
    @pytest.mark.parametrize("output,expected_errors", INVALID_OUTPUTS)
    def test_invalid_output_caught(self, output, expected_errors):
        errors = validate_scorer_output(output)
        assert len(errors) == len(expected_errors), (
            f"Expected {len(expected_errors)} errors, got {len(errors)}: {errors}"
        )
        for expected in expected_errors:
            assert any(expected in e for e in errors), (
                f"Expected error '{expected}' not found in {errors}"
            )


class TestJsonParsing:
    """Simulate the free-text → JSON parse step that Lever 4 replaces."""

    @pytest.mark.unit
    def test_clean_json_parses(self):
        raw = '{"best_mode": "OCR", "confidence": 0.88, "reasoning": "Clear scanned document with clean text"}'
        parsed = json.loads(raw)
        assert validate_scorer_output(parsed) == []

    @pytest.mark.unit
    def test_json_with_markdown_wrapper_fails(self):
        """LLMs often wrap JSON in ```json ... ```. Free-text path must strip this."""
        raw = '```json\n{"best_mode": "OCR", "confidence": 0.88, "reasoning": "Text"}\n```'
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)

    @pytest.mark.unit
    def test_json_strip_markdown_then_parse(self):
        """After stripping markdown fences, JSON should parse correctly."""
        raw = '```json\n{"best_mode": "OCR", "confidence": 0.88, "reasoning": "Valid reasoning text here"}\n```'
        stripped = raw.replace("```json\n", "").replace("\n```", "")
        parsed = json.loads(stripped)
        assert validate_scorer_output(parsed) == []

    @pytest.mark.unit
    def test_partial_json_raises(self):
        """Incomplete JSON (common in token-limit truncation) must fail."""
        raw = '{"best_mode": "OCR", "confidence": 0.88, "reasoning": "This is a long'
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)
