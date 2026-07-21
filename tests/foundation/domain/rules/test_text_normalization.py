from __future__ import annotations

import pytest

from knowledgenexus.foundation.domain.rules import TextNormalizationRules


def test_crlf_and_cr_become_lf() -> None:
    text = "alpha\r\nbeta\rgamma"

    assert TextNormalizationRules.normalize_text(text) == "alpha\nbeta\ngamma"


def test_trailing_whitespace_is_removed_per_line() -> None:
    text = "alpha  \n  beta\t\n    gamma   "

    assert TextNormalizationRules.normalize_text(text) == "alpha\n  beta\n    gamma"


def test_three_or_more_newlines_collapse_to_two_newlines() -> None:
    text = "alpha\n\n\n\nbeta"

    assert TextNormalizationRules.normalize_text(text) == "alpha\n\nbeta"


def test_leading_and_trailing_blank_lines_are_stripped() -> None:
    text = "\n \t\nalpha\nbeta\n   \n\n"

    assert TextNormalizationRules.normalize_text(text) == "alpha\nbeta"


def test_indentation_inside_non_blank_lines_is_preserved() -> None:
    text = "def example():\n    return 'value'\n\tindented"

    assert TextNormalizationRules.normalize_text(text) == text


def test_unicode_is_normalized_to_nfc_without_changing_case() -> None:
    text = "Tie\u0302\u0301ng Vie\u0323\u0302t\nSVMC Knowledge Δ"

    assert TextNormalizationRules.normalize_text(text) == "Tiếng Việt\nSVMC Knowledge Δ"


def test_non_string_input_fails() -> None:
    with pytest.raises(TypeError, match="expects text to be str"):
        TextNormalizationRules.normalize_text(123)  # type: ignore[arg-type]


def test_normalization_is_idempotent() -> None:
    text = "\r\nAlpha  \r\n\r\n\r\n\r\n  Beta\t\r\n"
    once = TextNormalizationRules.normalize_text(text)

    assert TextNormalizationRules.normalize_text(once) == once
