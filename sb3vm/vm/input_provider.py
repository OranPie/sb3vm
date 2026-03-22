from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


def normalize_key_name(value: str) -> str:
    text = value.strip().lower()
    aliases = {
        "space": "space",
        "spacebar": "space",
        "left arrow": "left arrow",
        "right arrow": "right arrow",
        "up arrow": "up arrow",
        "down arrow": "down arrow",
        "enter": "enter",
    }
    return aliases.get(text, text)


class InputProvider(Protocol):
    def key_pressed(self, key_name: str) -> bool: ...
    def active_keys(self) -> set[str]: ...
    def mouse_x(self) -> float: ...
    def mouse_y(self) -> float: ...
    def mouse_down(self) -> bool: ...
    def pop_answer(self) -> str | None: ...
    def current_answer(self) -> str: ...
    def set_answer(self, value: str) -> None: ...
    def timer_override(self, vm_elapsed_seconds: float) -> float | None: ...
    def snapshot(self) -> dict[str, object]: ...


@dataclass
class HeadlessInputProvider:
    pressed_keys: set[str] = field(default_factory=set)
    mouse_x_value: float = 0.0
    mouse_y_value: float = 0.0
    mouse_down_value: bool = False
    answers: list[str] = field(default_factory=list)
    answer_value: str = ""
    timer_override_value: float | None = None

    def key_pressed(self, key_name: str) -> bool:
        return normalize_key_name(key_name) in self.active_keys()

    def active_keys(self) -> set[str]:
        return {normalize_key_name(key) for key in self.pressed_keys}

    def mouse_x(self) -> float:
        return self.mouse_x_value

    def mouse_y(self) -> float:
        return self.mouse_y_value

    def mouse_down(self) -> bool:
        return self.mouse_down_value

    def pop_answer(self) -> str | None:
        if not self.answers:
            return None
        value = self.answers.pop(0)
        self.answer_value = value
        return value

    def current_answer(self) -> str:
        return self.answer_value

    def set_answer(self, value: str) -> None:
        self.answer_value = value

    def timer_override(self, vm_elapsed_seconds: float) -> float | None:
        return self.timer_override_value

    def snapshot(self) -> dict[str, object]:
        return {
            "answer": self.answer_value,
            "pending_answers": len(self.answers),
            "pressed_keys": sorted(self.active_keys()),
            "mouse_x": self.mouse_x_value,
            "mouse_y": self.mouse_y_value,
            "mouse_down": self.mouse_down_value,
            "timer_override": self.timer_override_value,
        }


@dataclass
class VmRng:
    seed: int | None = None

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)

    def randint(self, a: int, b: int) -> int:
        return self._random.randint(a, b)

    def uniform(self, a: float, b: float) -> float:
        return self._random.uniform(a, b)

    def randrange(self, stop: int) -> int:
        return self._random.randrange(stop)

