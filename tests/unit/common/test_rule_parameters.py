import pytest
from pydantic import ValidationError

from dq_scoring.common.rule_parameters import (
    JsonArrayParameters,
    JsonFieldParameters,
    SpellingParameters,
    TextQualityParameters,
)


def test_text_quality_parameters_valid():
    p1 = TextQualityParameters(column="text", check="REPLACEMENT_CHARACTER")
    assert p1.check == "REPLACEMENT_CHARACTER"

    p2 = TextQualityParameters(column="text", check="LENGTH", min_length=2, max_length=50)
    assert p2.min_length == 2
    assert p2.max_length == 50


def test_text_quality_parameters_invalid_length_bounds():
    with pytest.raises(ValidationError):
        # min_length > max_length
        TextQualityParameters(column="text", check="LENGTH", min_length=50, max_length=10)

    with pytest.raises(ValidationError):
        # Neither min_length nor max_length provided
        TextQualityParameters(column="text", check="LENGTH")


def test_spelling_parameters_valid_and_bounds():
    p = SpellingParameters(
        column="note",
        language="vi-en",
        dictionary_revision="rev-1",
        accepted_terms=["fintech", "giao dịch"],
    )
    assert p.language == "vi-en"
    assert len(p.accepted_terms) == 2

    # accepted_terms too long
    with pytest.raises(ValidationError):
        SpellingParameters(
            column="note",
            language="en",
            dictionary_revision="rev-1",
            accepted_terms=["a" * 129],
        )


def test_json_field_parameters_valid():
    p_type = JsonFieldParameters(column="payload", path="/user/age", check="TYPE", expected_type="NUMBER")
    assert p_type.expected_type == "NUMBER"

    p_range = JsonFieldParameters(column="payload", path="/amount", check="RANGE", min="0", max="1000.50")
    assert p_range.min == "0"

    p_regex = JsonFieldParameters(column="payload", path="/code", check="REGEX", pattern=r"^[A-Z]{3}$")
    assert p_regex.pattern == r"^[A-Z]{3}$"

    p_allowed = JsonFieldParameters(column="payload", path="/status", check="ALLOWED_VALUES", allowed_values=["A", "B"])
    assert p_allowed.allowed_values == ["A", "B"]


def test_json_field_parameters_invalid():
    # Bad RFC6901 path
    with pytest.raises(ValidationError):
        JsonFieldParameters(column="payload", path="no_slash", check="NON_NULL")

    # Missing expected_type
    with pytest.raises(ValidationError):
        JsonFieldParameters(column="payload", path="/a", check="TYPE")

    # Bad range
    with pytest.raises(ValidationError):
        JsonFieldParameters(column="payload", path="/a", check="RANGE", min="100", max="10")

    # Bad pattern length > 512
    with pytest.raises(ValidationError):
        JsonFieldParameters(column="payload", path="/a", check="REGEX", pattern="a" * 513)


def test_json_array_parameters_valid_and_invalid():
    p_arr = JsonArrayParameters(column="payload", path="/items", min_items=1, unique_items=True)
    assert p_arr.min_items == 1
    assert p_arr.unique_items is True

    # No constraint specified
    with pytest.raises(ValidationError):
        JsonArrayParameters(column="payload", path="/items")

    # min_items > max_items
    with pytest.raises(ValidationError):
        JsonArrayParameters(column="payload", path="/items", min_items=10, max_items=2)


@pytest.mark.parametrize("bound", ["NaN", "Infinity", "-Infinity"])
def test_json_range_requires_finite_bounds(bound):
    with pytest.raises(ValidationError):
        JsonFieldParameters(column="payload", path="/amount", check="RANGE", min=bound)


@pytest.mark.parametrize("path", ["/~2", "/trailing~"])
def test_pointer_rejects_invalid_escape(path):
    with pytest.raises(ValidationError):
        JsonFieldParameters(column="payload", path=path, check="NON_NULL")
