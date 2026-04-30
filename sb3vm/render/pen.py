"""Pen drawing layer for the MinimalRenderer.

Maintains a persistent RGBA canvas (480 × 360 in stage coordinates,
scaled to canvas pixels) that sprites paint on when their pen is down.
"""
from __future__ import annotations

from typing import Any


class PenLayer:
    """Persistent off-screen PIL canvas for pen strokes and stamps."""

    def __init__(self, width: int, height: int) -> None:
        from PIL import Image, ImageDraw

        self._width = width
        self._height = height
        self._image: Any = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        self._draw: Any = ImageDraw.Draw(self._image)
        self._dirty: bool = False

    def clear(self) -> None:
        from PIL import Image, ImageDraw

        self._image = Image.new("RGBA", (self._width, self._height), (0, 0, 0, 0))
        self._draw = ImageDraw.Draw(self._image)
        self._dirty = False

    def draw_line(
        self,
        from_cx: float,
        from_cy: float,
        to_cx: float,
        to_cy: float,
        color: tuple[int, int, int, int],
        size: float,
    ) -> None:
        width = max(1, int(round(size)))
        self._draw.line(
            [(from_cx, from_cy), (to_cx, to_cy)],
            fill=color,
            width=width,
        )
        if width > 1:
            # round line caps
            r = width / 2.0
            for px, py in [(from_cx, from_cy), (to_cx, to_cy)]:
                self._draw.ellipse(
                    [(px - r, py - r), (px + r, py + r)],
                    fill=color,
                )
        self._dirty = True

    def stamp_image(self, sprite_image: Any, cx: float, cy: float) -> None:
        """Composite *sprite_image* onto the pen layer at canvas center *cx, cy*."""
        x = int(round(cx - sprite_image.width / 2))
        y = int(round(cy - sprite_image.height / 2))
        self._image.alpha_composite(sprite_image.convert("RGBA"), (x, y))
        self._dirty = True

    def get_image(self) -> Any | None:
        """Return the pen layer PIL Image, or ``None`` if nothing was drawn."""
        return self._image if self._dirty else None
