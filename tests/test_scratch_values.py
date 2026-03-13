from __future__ import annotations

import pytest

from sb3vm.vm.scratch_values import (
    compare_equal,
    compare_order,
    letter_of,
    list_contains,
    list_contents,
    resolve_insert_index,
    resolve_list_index,
    to_bool,
    to_number,
    to_string,
)


def test_number_coercion_matches_scratch_style_defaults() -> None:
    assert to_number(None) == 0.0
    assert to_number("") == 0.0
    assert to_number("  ") == 0.0
    assert to_number("01") == 1.0
    assert to_number("1e2") == 100.0
    assert to_number("hello") == 0.0
    assert to_number(True) == 1.0
    assert to_number(False) == 0.0


def test_boolean_coercion_uses_scratch_truthiness() -> None:
    assert to_bool(True) is True
    assert to_bool(False) is False
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool("") is False
    assert to_bool("0") is False
    assert to_bool("false") is False
    assert to_bool("False ") is False
    assert to_bool("hello") is True


def test_stringification_and_comparisons_use_scratch_rules() -> None:
    assert to_string(True) == "true"
    assert to_string(False) == "false"
    assert to_string(12.0) == "12"
    assert to_string(12.5) == "12.5"
    assert compare_equal("01", 1) is True
    assert compare_equal("A", "a") is True
    assert compare_equal("true", True) is True
    assert compare_order("10", 2) == (10.0, 2.0)
    assert compare_order("cat", "Dog") == ("cat", "dog")


def test_list_index_resolution_handles_special_and_invalid_cases() -> None:
    random_index = lambda length: length - 1

    assert resolve_list_index(1, 3, random_index=random_index) == 0
    assert resolve_list_index("last", 3, random_index=random_index) == 2
    assert resolve_list_index("random", 3, random_index=random_index) == 2
    assert resolve_list_index("any", 3, random_index=random_index) == 2
    assert resolve_list_index(0, 3, random_index=random_index) is None
    assert resolve_list_index(4, 3, random_index=random_index) is None
    assert resolve_list_index("last", 0, random_index=random_index) is None
    assert resolve_list_index("random", 0, random_index=random_index) is None


def test_insert_index_clamps_like_scratch_lists() -> None:
    random_index = lambda length: 1

    assert resolve_insert_index(0, 3, random_index=random_index) == 0
    assert resolve_insert_index(1, 3, random_index=random_index) == 0
    assert resolve_insert_index(2, 3, random_index=random_index) == 1
    assert resolve_insert_index(99, 3, random_index=random_index) == 3
    assert resolve_insert_index("last", 3, random_index=random_index) == 3
    assert resolve_insert_index("random", 3, random_index=random_index) == 1
    assert resolve_insert_index("random", 0, random_index=random_index) == 0


def test_missing_reporters_and_list_helpers_return_scratch_fallbacks() -> None:
    assert letter_of(1, "") == ""
    assert letter_of(9, "cat") == ""
    assert list_contains([1, "2", True], "1") is True
    assert list_contains([1, "2", True], "true") is True
    assert list_contents([1, "two", True]) == "1 two true"
