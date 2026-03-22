from __future__ import annotations

import math
from typing import Any, Callable
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


RandomIndexFn = Callable[[int], int]


def to_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0 and not math.isnan(value)
    text = str(value).strip().lower()
    return text not in {"", "0", "false"}


def to_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def _numeric_value(value: Any) -> float | None:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def compare_equal(a: Any, b: Any) -> bool:
    left = _numeric_value(a)
    right = _numeric_value(b)
    if left is not None and right is not None:
        return left == right
    return to_string(a).lower() == to_string(b).lower()


def compare_order(a: Any, b: Any) -> tuple[Any, Any]:
    left = _numeric_value(a)
    right = _numeric_value(b)
    if left is not None and right is not None:
        return left, right
    return to_string(a).lower(), to_string(b).lower()


def resolve_list_index(
    index: Any,
    length: int,
    *,
    random_index: RandomIndexFn | None = None,
) -> int | None:
    if isinstance(index, str):
        lowered = index.strip().lower()
        if lowered == "last":
            return length - 1 if length else None
        if lowered in {"random", "any"}:
            return random_index(length) if length and random_index is not None else None
    resolved = int(to_number(index)) - 1
    if resolved < 0 or resolved >= length:
        return None
    return resolved


def resolve_insert_index(
    index: Any,
    length: int,
    *,
    random_index: RandomIndexFn | None = None,
) -> int:
    if isinstance(index, str):
        lowered = index.strip().lower()
        if lowered == "last":
            return length
        if lowered in {"random", "any"}:
            if length and random_index is not None:
                return random_index(length)
            return 0
    resolved = int(to_number(index))
    if resolved <= 1:
        return 0
    if resolved > length + 1:
        return length
    return resolved - 1


def list_contains(items: list[Any], needle: Any) -> bool:
    return any(compare_equal(item, needle) for item in items)


def list_contents(items: list[Any]) -> str:
    return " ".join(to_string(item) for item in items)


def letter_of(index: Any, value: Any) -> str:
    resolved = int(to_number(index)) - 1
    text = to_string(value)
    return text[resolved] if 0 <= resolved < len(text) else ""

