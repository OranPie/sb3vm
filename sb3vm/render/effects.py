"""Graphic effect pipeline for Scratch sprites and backdrops.

All seven Scratch effects are implemented here.  The two warp effects
(whirl and fisheye) use numpy coordinate remapping instead of per-pixel
Python loops, giving roughly 100× speedup on typical sprite sizes.
"""
from __future__ import annotations

import math
from typing import Any


def apply_graphic_effects(image: Any, effects: dict[str, Any]) -> Any:
    """Apply all active graphic effects to *image* and return the result.

    Non-zero values are applied in Scratch's canonical order.
    *image* must be a PIL Image (any mode; it will be converted to RGBA
    internally).
    """
    if not effects:
        return image
    rendered = image.convert("RGBA")
    color_val = _effect_number(effects.get("color"))
    if color_val:
        rendered = _apply_color(rendered, color_val)
    brightness_val = _effect_number(effects.get("brightness"))
    if brightness_val:
        rendered = _apply_brightness(rendered, brightness_val)
    pixelate_val = _effect_number(effects.get("pixelate"))
    if pixelate_val:
        rendered = _apply_pixelate(rendered, pixelate_val)
    mosaic_val = _effect_number(effects.get("mosaic"))
    if mosaic_val:
        rendered = _apply_mosaic(rendered, mosaic_val)
    whirl_val = _effect_number(effects.get("whirl"))
    if whirl_val:
        rendered = _apply_whirl(rendered, whirl_val)
    fisheye_val = _effect_number(effects.get("fisheye"))
    if fisheye_val:
        rendered = _apply_fisheye(rendered, fisheye_val)
    ghost_val = _effect_number(effects.get("ghost"))
    if ghost_val:
        rendered = _apply_ghost(rendered, ghost_val)
    return rendered


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _effect_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _apply_color(image: Any, value: float) -> Any:
    """Hue-shift by *value* / 200 of a full rotation."""
    import numpy as np
    from PIL import Image

    arr = np.array(image, dtype=np.uint8)
    alpha = arr[:, :, 3].copy()
    rgb = Image.fromarray(arr[:, :, :3], "RGB").convert("HSV")
    hsv = np.array(rgb, dtype=np.int32)
    shift = int(round((value / 200.0) * 255.0)) % 256
    hsv[:, :, 0] = (hsv[:, :, 0] + shift) % 256
    colored = Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGBA")
    out = np.array(colored, dtype=np.uint8)
    out[:, :, 3] = alpha
    return Image.fromarray(out, "RGBA")


def _apply_brightness(image: Any, value: float) -> Any:
    """Lighten (value > 0) or darken (value < 0) by 0–100%."""
    import numpy as np
    from PIL import Image

    arr = np.array(image, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    if value >= 0:
        factor = min(value, 100.0) / 100.0
        rgb = rgb + (255.0 - rgb) * factor
    else:
        factor = max(0.0, 1.0 + max(value, -100.0) / 100.0)
        rgb = rgb * factor
    out = np.clip(np.round(arr), 0, 255).astype(np.uint8)
    out[:, :, :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    out[:, :, 3] = alpha.astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _apply_ghost(image: Any, value: float) -> Any:
    """Scale alpha channel by (1 - value/100) clamped to [0, 1]."""
    import numpy as np
    from PIL import Image

    factor = max(0.0, 1.0 - min(max(value, 0.0), 100.0) / 100.0)
    arr = np.array(image, dtype=np.float32)
    arr[:, :, 3] = np.clip(np.round(arr[:, :, 3] * factor), 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _apply_pixelate(image: Any, value: float) -> Any:
    """Block-pixelate the image."""
    from PIL import Image

    block = max(1, int(abs(value) / 10.0) + 1)
    w = max(1, image.width // block)
    h = max(1, image.height // block)
    resampling = getattr(Image, "Resampling", Image)
    return image.resize((w, h), resampling.BOX).resize((image.width, image.height), resampling.NEAREST)


def _apply_mosaic(image: Any, value: float) -> Any:
    """Tile the image *n × n* times."""
    from PIL import Image

    cells = max(1, int(abs(value) / 10.0) + 1)
    tw = max(1, image.width // cells)
    th = max(1, image.height // cells)
    resampling = getattr(Image, "Resampling", Image)
    tile = image.resize((tw, th), resampling.BOX)
    mosaic = Image.new("RGBA", image.size, (0, 0, 0, 0))
    for x in range(0, image.width, tw):
        for y in range(0, image.height, th):
            mosaic.alpha_composite(tile, (x, y))
    return mosaic


def _apply_whirl(image: Any, value: float) -> Any:
    """Whirl/swirl the image by *value* degrees at the center."""
    import numpy as np
    from PIL import Image

    src = np.array(image.convert("RGBA"), dtype=np.uint8)
    H, W = src.shape[:2]
    dst = np.zeros_like(src)
    cx = (W - 1) / 2.0
    cy = (H - 1) / 2.0
    max_r = max(1.0, min(W, H) / 2.0)

    gy, gx = np.mgrid[0:H, 0:W].astype(np.float64)
    dx = gx - cx
    dy = gy - cy
    radius = np.hypot(dx, dy) / max_r
    inside = radius < 1.0
    angle = np.where(inside, math.radians(value) * (1.0 - radius) ** 2, 0.0)
    cos_a = np.cos(-angle)
    sin_a = np.sin(-angle)
    sx = np.where(inside, cx + dx * cos_a - dy * sin_a, gx)
    sy = np.where(inside, cy + dx * sin_a + dy * cos_a, gy)
    sx = np.clip(np.round(sx).astype(np.int32), 0, W - 1)
    sy = np.clip(np.round(sy).astype(np.int32), 0, H - 1)
    dst = src[sy, sx]
    return Image.fromarray(dst, "RGBA")


def _apply_fisheye(image: Any, value: float) -> Any:
    """Bulge (value > 0) or pinch (value < 0) the image."""
    import numpy as np
    from PIL import Image

    src = np.array(image.convert("RGBA"), dtype=np.uint8)
    H, W = src.shape[:2]
    cx = (W - 1) / 2.0
    cy = (H - 1) / 2.0
    max_r = max(1.0, min(W, H) / 2.0)

    gy, gx = np.mgrid[0:H, 0:W].astype(np.float64)
    dx = gx - cx
    dy = gy - cy
    radius = np.hypot(dx, dy) / max_r
    power = max(0.2, 1.0 + value / 100.0)
    valid = (radius > 0.0) & (radius < 1.0)
    scale = np.where(valid, (radius ** power) / np.where(radius > 0, radius, 1.0), 1.0)
    sx = np.clip(np.round(cx + dx * scale).astype(np.int32), 0, W - 1)
    sy = np.clip(np.round(cy + dy * scale).astype(np.int32), 0, H - 1)
    dst = src[sy, sx]
    return Image.fromarray(dst, "RGBA")
