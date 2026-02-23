"""Tests for Variant ID Validation (Section 4.7)."""

from __future__ import annotations

from src.engine.variant_check import MATCH, VARIANT_MISMATCH, validate_variant


def test_validate_variant_returns_match_for_identical_ids() -> None:
    """Section 4.7: exact canonical ID match must pass Layer 2 first filter."""
    result = validate_variant("sv1-25", "sv1-25")
    assert result == MATCH


def test_validate_variant_returns_mismatch_for_different_ids() -> None:
    """Section 4.7: different variants must be suppressed as VARIANT_MISMATCH."""
    result = validate_variant("sv1-25", "svp-25")
    assert result == VARIANT_MISMATCH


def test_validate_variant_returns_mismatch_for_empty_or_none_ids() -> None:
    """Section 4.7: unresolved or missing IDs must be treated as mismatches."""
    empty_result = validate_variant("", "sv1-25")
    none_result = validate_variant(None, "sv1-25")  # type: ignore[arg-type]

    assert empty_result == VARIANT_MISMATCH
    assert none_result == VARIANT_MISMATCH

