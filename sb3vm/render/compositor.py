"""Headless scene compositor for pixel-level collision detection.

Used to implement ``touching_color`` and ``color_touching_color`` blocks.
The compositor builds a full PIL RGBA image of the scene (stage + pen +
sprites in draw order) without requiring a Tkinter window, then answers
color queries using numpy vectorised comparison.
"""
from __future__ import annotations

import math
from typing import Any

from sb3vm.render.assets import RenderAssetStore
from sb3vm.render.effects import apply_graphic_effects


_COLOR_TOLERANCE = 3  # per-channel tolerance for colour matching


class Compositor:
    """Headless PIL scene compositor.

    Parameters
    ----------
    asset_store:
        Shared asset store from the renderer.
    scale:
        Display scale factor (1.0 = 480 × 360).
    """

    def __init__(self, asset_store: RenderAssetStore, scale: float = 1.0) -> None:
        self._assets = asset_store
        self._scale = scale
        # Per-step cache
        self._cache_step: int = -1
        self._cache_scene: Any | None = None

    def invalidate(self) -> None:
        """Discard the cached composited scene (call once per VM step)."""
        self._cache_step = -1
        self._cache_scene = None

    def get_scene(self, snapshot: dict[str, Any], pen_image: Any | None = None) -> Any:
        """Return a composited PIL Image for *snapshot*.

        Results are memoised for the current step; call :meth:`invalidate`
        at the start of each step to refresh.
        """
        if self._cache_scene is not None:
            return self._cache_scene
        scene = self.composite_scene(snapshot, pen_image=pen_image)
        self._cache_scene = scene
        return scene

    def composite_scene(
        self,
        snapshot: dict[str, Any],
        pen_image: Any | None = None,
        exclude_instance_id: int | None = None,
    ) -> Any:
        """Composite stage + pen + sprites into a single RGBA PIL Image."""
        from PIL import Image

        stage_info = snapshot.get("stage", {})
        coord = snapshot.get("coordinate_system", {})
        stage_w = int(coord.get("stage_width", 480))
        stage_h = int(coord.get("stage_height", 360))
        cw = max(1, int(stage_w * self._scale))
        ch = max(1, int(stage_h * self._scale))

        scene = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))

        # Stage backdrop
        backdrop = stage_info.get("backdrop", {})
        stage_img = self._assets.load_image(backdrop)
        if stage_img is not None:
            stage_eff = apply_graphic_effects(stage_img, stage_info.get("effects", {}))
            scene.alpha_composite(
                stage_eff.resize((cw, ch)).convert("RGBA"),
                (0, 0),
            )

        # Pen layer
        if pen_image is not None:
            scene.alpha_composite(pen_image.convert("RGBA"), (0, 0))

        # Sprites in draw order
        resampling = getattr(Image, "Resampling", Image)
        for drawable in snapshot.get("drawables", []):
            if not drawable.get("visible", False):
                continue
            if exclude_instance_id is not None and drawable.get("instance_id") == exclude_instance_id:
                continue
            sprite_img = self._render_drawable(drawable, resampling)
            if sprite_img is None:
                continue
            cx, cy = self._to_canvas(
                drawable["position"]["x"],
                drawable["position"]["y"],
                stage_w,
                stage_h,
            )
            anchor_x, anchor_y = self._anchor_offset(sprite_img, drawable)
            paste_x = int(round(cx - anchor_x - sprite_img.width / 2))
            paste_y = int(round(cy - anchor_y - sprite_img.height / 2))
            scene.alpha_composite(sprite_img, (max(0, paste_x), max(0, paste_y)))

        return scene

    # ------------------------------------------------------------------
    # Color collision helpers
    # ------------------------------------------------------------------

    def _find_drawable(self, snapshot: dict[str, Any], instance_id: int) -> dict[str, Any] | None:
        for d in snapshot.get("drawables", []):
            if d.get("instance_id") == instance_id:
                return d
        return None

    def check_touching_color(
        self,
        snapshot: dict[str, Any],
        instance_id: int,
        target_rgb: tuple[int, int, int],
        drawable: dict[str, Any] | None = None,
        pen_image: Any | None = None,
        tolerance: int = _COLOR_TOLERANCE,
    ) -> bool:
        """Return True if any non-transparent pixel of the sprite touches *target_rgb*."""
        import numpy as np
        from PIL import Image

        if drawable is None:
            drawable = self._find_drawable(snapshot, instance_id)
        if drawable is None:
            return False

        # Scene without the querying sprite
        scene = self.composite_scene(snapshot, pen_image=pen_image, exclude_instance_id=instance_id)

        resampling = getattr(Image, "Resampling", Image)
        sprite_img = self._render_drawable(drawable, resampling)
        if sprite_img is None:
            return False

        coord = snapshot.get("coordinate_system", {})
        stage_w = int(coord.get("stage_width", 480))
        stage_h = int(coord.get("stage_height", 360))
        cx, cy = self._to_canvas(drawable["position"]["x"], drawable["position"]["y"], stage_w, stage_h)
        anchor_x, anchor_y = self._anchor_offset(sprite_img, drawable)
        left = int(round(cx - anchor_x - sprite_img.width / 2))
        top = int(round(cy - anchor_y - sprite_img.height / 2))

        sprite_arr = np.array(sprite_img.convert("RGBA"), dtype=np.uint8)
        scene_arr = np.array(scene, dtype=np.uint8)

        return _pixels_touch_color(sprite_arr, scene_arr, left, top, target_rgb, tolerance)

    def check_color_touching_color(
        self,
        snapshot: dict[str, Any],
        instance_id: int,
        sprite_rgb: tuple[int, int, int],
        scene_rgb: tuple[int, int, int],
        drawable: dict[str, Any] | None = None,
        pen_image: Any | None = None,
        tolerance: int = _COLOR_TOLERANCE,
    ) -> bool:
        """Return True if pixels of colour *sprite_rgb* on the sprite overlap
        pixels of colour *scene_rgb* on the scene (excluding the sprite itself)."""
        import numpy as np
        from PIL import Image

        if drawable is None:
            drawable = self._find_drawable(snapshot, instance_id)
        if drawable is None:
            return False

        scene = self.composite_scene(snapshot, pen_image=pen_image, exclude_instance_id=instance_id)

        resampling = getattr(Image, "Resampling", Image)
        sprite_img = self._render_drawable(drawable, resampling)
        if sprite_img is None:
            return False

        coord = snapshot.get("coordinate_system", {})
        stage_w = int(coord.get("stage_width", 480))
        stage_h = int(coord.get("stage_height", 360))
        cx, cy = self._to_canvas(drawable["position"]["x"], drawable["position"]["y"], stage_w, stage_h)
        anchor_x, anchor_y = self._anchor_offset(sprite_img, drawable)
        left = int(round(cx - anchor_x - sprite_img.width / 2))
        top = int(round(cy - anchor_y - sprite_img.height / 2))

        sprite_arr = np.array(sprite_img.convert("RGBA"), dtype=np.uint8)
        scene_arr = np.array(scene, dtype=np.uint8)

        return _color_pixels_touch_color(sprite_arr, scene_arr, left, top, sprite_rgb, scene_rgb, tolerance)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_canvas(self, x: float, y: float, stage_w: int, stage_h: int) -> tuple[float, float]:
        cw = stage_w * self._scale
        ch = stage_h * self._scale
        return (x + stage_w / 2) * self._scale, (stage_h / 2 - y) * self._scale

    def _anchor_offset(self, image: Any, drawable: dict[str, Any]) -> tuple[float, float]:
        """Return the (dx, dy) offset of the rotation center from the rendered image center."""
        costume = drawable.get("costume", {})
        rc_x = float(costume.get("rotationCenterX") or 0.0)
        rc_y = float(costume.get("rotationCenterY") or 0.0)
        # Native (unscaled) image dimensions from the original costume asset
        native_w = float(costume.get("native_width") or image.width / (max(0.01, drawable.get("size", 100.0)) / 100.0) / self._scale)
        native_h = float(costume.get("native_height") or image.height / (max(0.01, drawable.get("size", 100.0)) / 100.0) / self._scale)
        size_scale = max(0.0, drawable.get("size", 100.0) / 100.0) * self._scale
        ox = (rc_x - native_w / 2) * size_scale
        oy = (rc_y - native_h / 2) * size_scale
        rotation_style = str(drawable.get("rotation_style", "all around")).strip().lower()
        direction = float(drawable.get("direction", 90.0))
        if rotation_style == "don't rotate":
            return (ox, oy)
        if rotation_style == "left-right":
            if direction < 0:
                return (-ox, oy)
            return (ox, oy)
        angle_deg = (90.0 - direction) % 360.0
        if angle_deg == 0.0:
            return (ox, oy)
        a = math.radians(angle_deg)
        return (ox * math.cos(a) - oy * math.sin(a), ox * math.sin(a) + oy * math.cos(a))

    def _render_drawable(self, drawable: dict[str, Any], resampling: Any) -> Any | None:
        from PIL import Image, ImageOps

        costume = drawable.get("costume", {})
        image = self._assets.load_image(costume)
        if image is None:
            return None
        size_scale = max(0.0, drawable.get("size", 100.0) / 100.0) * self._scale
        w = max(1, int(image.width * size_scale))
        h = max(1, int(image.height * size_scale))
        rendered = image.resize((w, h))
        rotation_style = str(drawable.get("rotation_style", "all around")).strip().lower()
        direction = float(drawable.get("direction", 90.0))
        if rotation_style == "left-right":
            if direction < 0:
                rendered = ImageOps.mirror(rendered)
        elif rotation_style != "don't rotate":
            angle = (90.0 - direction) % 360.0
            if angle != 0.0:
                rendered = rendered.rotate(angle, expand=True)
        rendered = apply_graphic_effects(rendered, drawable.get("effects", {}))
        return rendered.convert("RGBA")


# ------------------------------------------------------------------
# numpy pixel helpers (module-level for reuse)
# ------------------------------------------------------------------

def _pixels_touch_color(
    sprite_arr: Any,
    scene_arr: Any,
    left: int,
    top: int,
    target_rgb: tuple[int, int, int],
    tolerance: int,
) -> bool:
    import numpy as np

    sh, sw = sprite_arr.shape[:2]
    ssh, ssw = scene_arr.shape[:2]
    # Intersection region
    x0 = max(0, left)
    y0 = max(0, top)
    x1 = min(ssw, left + sw)
    y1 = min(ssh, top + sh)
    if x0 >= x1 or y0 >= y1:
        return False
    sx0, sy0 = x0 - left, y0 - top
    sprite_crop = sprite_arr[sy0: sy0 + (y1 - y0), sx0: sx0 + (x1 - x0)]
    scene_crop = scene_arr[y0:y1, x0:x1]
    opaque = sprite_crop[:, :, 3] > 0
    tr, tg, tb = target_rgb
    sr, sg, sb = scene_crop[:, :, 0], scene_crop[:, :, 1], scene_crop[:, :, 2]
    match = (
        opaque
        & (np.abs(sr.astype(np.int16) - tr) <= tolerance)
        & (np.abs(sg.astype(np.int16) - tg) <= tolerance)
        & (np.abs(sb.astype(np.int16) - tb) <= tolerance)
    )
    return bool(np.any(match))


def _color_pixels_touch_color(
    sprite_arr: Any,
    scene_arr: Any,
    left: int,
    top: int,
    sprite_rgb: tuple[int, int, int],
    scene_rgb: tuple[int, int, int],
    tolerance: int,
) -> bool:
    import numpy as np

    sh, sw = sprite_arr.shape[:2]
    ssh, ssw = scene_arr.shape[:2]
    x0 = max(0, left)
    y0 = max(0, top)
    x1 = min(ssw, left + sw)
    y1 = min(ssh, top + sh)
    if x0 >= x1 or y0 >= y1:
        return False
    sx0, sy0 = x0 - left, y0 - top
    sprite_crop = sprite_arr[sy0: sy0 + (y1 - y0), sx0: sx0 + (x1 - x0)]
    scene_crop = scene_arr[y0:y1, x0:x1]

    sr, sg, sb = sprite_rgb
    sprite_match = (
        (sprite_crop[:, :, 3] > 0)
        & (np.abs(sprite_crop[:, :, 0].astype(np.int16) - sr) <= tolerance)
        & (np.abs(sprite_crop[:, :, 1].astype(np.int16) - sg) <= tolerance)
        & (np.abs(sprite_crop[:, :, 2].astype(np.int16) - sb) <= tolerance)
    )
    cr, cg, cb = scene_rgb
    scene_match = (
        (np.abs(scene_crop[:, :, 0].astype(np.int16) - cr) <= tolerance)
        & (np.abs(scene_crop[:, :, 1].astype(np.int16) - cg) <= tolerance)
        & (np.abs(scene_crop[:, :, 2].astype(np.int16) - cb) <= tolerance)
    )
    return bool(np.any(sprite_match & scene_match))
