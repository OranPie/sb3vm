"""Speech-bubble / thought-bubble overlay for the MinimalRenderer.

All drawing uses Tkinter canvas primitives so no extra PIL compositing
is required in the hot paint path.
"""
from __future__ import annotations

import math
from typing import Any


_BUBBLE_PAD_X = 8
_BUBBLE_PAD_Y = 6
_BUBBLE_RADIUS = 8
_BUBBLE_MAX_WIDTH = 180
_FONT_SIZE = 13  # approximate pixel height per line (Tkinter default font)
_LINE_HEIGHT = _FONT_SIZE + 4
_POINTER_HEIGHT = 12
_POINTER_WIDTH = 14


def paint_speech_bubble(
    canvas: Any,
    drawable: dict[str, Any],
    mapper: Any,
) -> None:
    """Draw a say/think bubble above the sprite described by *drawable*."""
    dialogue = drawable.get("dialogue")
    if not dialogue:
        return
    text = str(dialogue.get("text") or "")
    style = str(dialogue.get("style") or "say").lower()
    if not text:
        return

    cx, cy = mapper.to_canvas(
        drawable["position"]["x"],
        drawable["position"]["y"],
    )
    lines = _wrap_text(text, _BUBBLE_MAX_WIDTH)
    box_w = min(_BUBBLE_MAX_WIDTH, max(len(line) * 7 for line in lines) + _BUBBLE_PAD_X * 2)
    box_h = len(lines) * _LINE_HEIGHT + _BUBBLE_PAD_Y * 2

    # Position bubble above-right of sprite center
    bx = cx + 4
    by = cy - box_h - _POINTER_HEIGHT - 4

    if style == "think":
        _paint_think_bubble(canvas, bx, by, box_w, box_h, cx, cy, lines)
    else:
        _paint_say_bubble(canvas, bx, by, box_w, box_h, cx, cy, lines)


def _wrap_text(text: str, max_width: int) -> list[str]:
    approx_chars = max(10, max_width // 7)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if len(candidate) <= approx_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _paint_say_bubble(
    canvas: Any,
    bx: float,
    by: float,
    box_w: float,
    box_h: float,
    sprite_cx: float,
    sprite_cy: float,
    lines: list[str],
) -> None:
    r = _BUBBLE_RADIUS
    # Rounded rectangle
    canvas.create_rectangle(
        bx + r, by,
        bx + box_w - r, by + box_h,
        fill="white", outline="#555555", width=1,
    )
    canvas.create_rectangle(
        bx, by + r,
        bx + box_w, by + box_h - r,
        fill="white", outline="",
    )
    # Corners
    for (ox, oy), (start, extent) in [
        ((bx, by), (90, 90)),
        ((bx + box_w - 2 * r, by), (0, 90)),
        ((bx, by + box_h - 2 * r), (180, 90)),
        ((bx + box_w - 2 * r, by + box_h - 2 * r), (270, 90)),
    ]:
        canvas.create_arc(
            ox, oy, ox + 2 * r, oy + 2 * r,
            start=start, extent=extent,
            fill="white", outline="#555555", width=1,
        )
    # Pointer triangle
    tip_x = max(bx + 10, min(sprite_cx, bx + box_w - 10))
    tip_y = sprite_cy - 4
    canvas.create_polygon(
        tip_x - _POINTER_WIDTH // 2, by + box_h,
        tip_x + _POINTER_WIDTH // 2, by + box_h,
        tip_x, tip_y,
        fill="white", outline="#555555",
    )
    _draw_bubble_text(canvas, bx, by, box_w, lines)


def _paint_think_bubble(
    canvas: Any,
    bx: float,
    by: float,
    box_w: float,
    box_h: float,
    sprite_cx: float,
    sprite_cy: float,
    lines: list[str],
) -> None:
    r = max(box_w, box_h) / 2.0
    oval_cx = bx + box_w / 2.0
    oval_cy = by + box_h / 2.0
    canvas.create_oval(
        oval_cx - box_w / 2, oval_cy - box_h / 2,
        oval_cx + box_w / 2, oval_cy + box_h / 2,
        fill="white", outline="#555555", width=1,
    )
    # Thought dots leading down to sprite
    dot_cx = max(bx + 8, min(sprite_cx, bx + box_w - 8))
    dot_cy = by + box_h
    for i, (dr, dy_offset) in enumerate([(5, 10), (4, 20), (3, 28)]):
        canvas.create_oval(
            dot_cx - dr, dot_cy + dy_offset - dr,
            dot_cx + dr, dot_cy + dy_offset + dr,
            fill="white", outline="#555555", width=1,
        )
    _draw_bubble_text(canvas, bx, by, box_w, lines)


def _draw_bubble_text(
    canvas: Any,
    bx: float,
    by: float,
    box_w: float,
    lines: list[str],
) -> None:
    for i, line in enumerate(lines):
        canvas.create_text(
            bx + box_w / 2,
            by + _BUBBLE_PAD_Y + i * _LINE_HEIGHT + _FONT_SIZE / 2,
            text=line,
            fill="#333333",
            anchor="center",
        )
