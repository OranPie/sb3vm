from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from sb3vm.log import debug, get_logger, info, trace
from sb3vm.model.project import Project
from sb3vm.render.assets import RenderAssetStore, RendererDependencyError, RendererError
from sb3vm.vm.input_provider import HeadlessInputProvider, InteractiveInputProvider
from sb3vm.vm.runtime import Sb3Vm


_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class ScratchCoordinateMapper:
    stage_width: int = 480
    stage_height: int = 360
    scale: float = 1.0

    @property
    def canvas_width(self) -> int:
        return int(self.stage_width * self.scale)

    @property
    def canvas_height(self) -> int:
        return int(self.stage_height * self.scale)

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (
            (x + self.stage_width / 2) * self.scale,
            (self.stage_height / 2 - y) * self.scale,
        )

    def to_stage(self, canvas_x: float, canvas_y: float) -> tuple[float, float]:
        x = canvas_x / self.scale - self.stage_width / 2
        y = self.stage_height / 2 - canvas_y / self.scale
        return (x, y)


@dataclass
class MinimalRenderer:
    project: Project
    vm: Sb3Vm
    scale: float = 1.0
    fps: int = 30
    show_monitors: bool = False
    asset_store: RenderAssetStore = field(init=False)

    def __post_init__(self) -> None:
        self.asset_store = RenderAssetStore(self.project)
        self.mapper = ScratchCoordinateMapper(scale=self.scale)
        self._canvas = None
        self._root = None
        self._image_refs: list[Any] = []
        self._rendered_image_cache: dict[tuple[Any, ...], Any] = {}
        self._tk_image_cache: dict[tuple[Any, ...], Any] = {}
        self._last_render_snapshot: dict[str, Any] | None = None
        self._started = False
        self._image_tk = None
        self._prompt_frame = None
        self._prompt_label = None
        self._prompt_entry = None
        self._prompt_button = None
        self._prompt_visible = False
        self.input_provider = self._ensure_interactive_input_provider()

    def run(self, *, seconds: float | None = None, dt: float = 1 / 30) -> None:
        try:
            import tkinter as tk
            from PIL import ImageTk
        except ModuleNotFoundError as exc:
            raise RendererDependencyError(
                "Display mode requires tkinter and Pillow. Install render extras and use a GUI-capable environment."
            ) from exc

        try:
            self._root = tk.Tk()
        except tk.TclError as exc:
            raise RendererError("Unable to open a display window in this environment.") from exc

        self._root.title("sb3vm")
        self._canvas = tk.Canvas(
            self._root,
            width=self.mapper.canvas_width,
            height=self.mapper.canvas_height,
            highlightthickness=0,
            bg="white",
        )
        self._canvas.pack()
        self._image_tk = ImageTk
        self._build_prompt_ui(tk)
        self._bind_inputs()
        self._maybe_start_vm()
        self._paint(self.vm.render_snapshot())
        if seconds is not None and seconds <= 0:
            self._root.after(0, self._root.destroy)
        else:
            self._schedule_frame(seconds=seconds, dt=dt, elapsed=0.0)
        self._root.mainloop()

    def _ensure_interactive_input_provider(self) -> InteractiveInputProvider:
        provider = self.vm.input_provider
        if isinstance(provider, InteractiveInputProvider):
            return provider
        interactive = InteractiveInputProvider()
        if isinstance(provider, HeadlessInputProvider):
            interactive.pressed_keys = set(provider.pressed_keys)
            interactive.mouse_x_value = provider.mouse_x_value
            interactive.mouse_y_value = provider.mouse_y_value
            interactive.mouse_down_value = provider.mouse_down_value
            interactive.answers = list(provider.answers)
            interactive.answer_value = provider.answer_value
            interactive.timer_override_value = provider.timer_override_value
        self.vm.input_provider = interactive
        debug(_LOGGER, "render.MinimalRenderer._ensure_interactive_input_provider", "attached interactive input provider")
        return interactive

    def _build_prompt_ui(self, tk: Any) -> None:
        assert self._root is not None
        self._prompt_frame = tk.Frame(self._root)
        self._prompt_label = tk.Label(self._prompt_frame, text="", anchor="w")
        self._prompt_label.pack(side="left", padx=(0, 8))
        self._prompt_entry = tk.Entry(self._prompt_frame)
        self._prompt_entry.pack(side="left", fill="x", expand=True)
        self._prompt_entry.bind("<Return>", self._submit_answer)
        self._prompt_button = tk.Button(self._prompt_frame, text="Send", command=self._submit_answer)
        self._prompt_button.pack(side="left", padx=(8, 0))

    def _bind_inputs(self) -> None:
        assert self._root is not None
        assert self._canvas is not None
        self._root.bind("<KeyPress>", self._on_key_press)
        self._root.bind("<KeyRelease>", self._on_key_release)
        self._canvas.bind("<Motion>", self._on_mouse_motion)
        self._canvas.bind("<B1-Motion>", self._on_mouse_motion)
        self._canvas.bind("<ButtonPress-1>", self._on_mouse_press)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_release)
        self._canvas.bind("<Leave>", self._on_mouse_leave)
        self._canvas.focus_set()

    def _schedule_frame(self, *, seconds: float | None, dt: float, elapsed: float) -> None:
        assert self._root is not None

        def tick() -> None:
            next_elapsed = elapsed
            if seconds is None or elapsed < seconds:
                self.vm.step(dt)
                next_elapsed += dt
                self._paint(self.vm.render_snapshot())
            if seconds is not None and next_elapsed >= seconds:
                self._root.destroy()
                return
            self._root.after(max(1, int(1000 / self.fps)), lambda: self._schedule_frame(seconds=seconds, dt=dt, elapsed=next_elapsed))

        self._root.after(max(1, int(1000 / self.fps)), tick)

    def _maybe_start_vm(self) -> None:
        if not self._started:
            self.vm.start_green_flag()
            self._started = True

    def _paint(self, snapshot: dict[str, Any]) -> None:
        assert self._canvas is not None
        self._last_render_snapshot = snapshot
        self._canvas.delete("all")
        self._image_refs.clear()
        self._paint_stage(snapshot["stage"])
        for drawable in snapshot["drawables"]:
            self._paint_drawable(drawable)
        if self.show_monitors:
            self._paint_monitors()
        self._sync_prompt(snapshot)

    def _paint_stage(self, stage: dict[str, Any]) -> None:
        assert self._canvas is not None
        image = self._stage_tk_image(stage)
        if image is None:
            return
        self._image_refs.append(image)
        self._canvas.create_image(0, 0, image=image, anchor="nw")

    def _paint_drawable(self, drawable: dict[str, Any]) -> None:
        assert self._canvas is not None
        if not drawable["visible"]:
            return
        tk_image = self._drawable_tk_image(drawable)
        if tk_image is None:
            return
        self._image_refs.append(tk_image)
        x, y = self.mapper.to_canvas(drawable["position"]["x"], drawable["position"]["y"])
        self._canvas.create_image(x, y, image=tk_image, anchor="center")

    def _stage_tk_image(self, stage: dict[str, Any]) -> Any | None:
        backdrop = stage.get("backdrop", {})
        cache_key = (
            "stage",
            backdrop.get("md5ext"),
            self.mapper.canvas_width,
            self.mapper.canvas_height,
            self._effects_cache_key(stage.get("effects", {})),
        )
        cached = self._tk_image_cache.get(cache_key)
        if cached is not None:
            return cached
        image = self.asset_store.load_image(backdrop)
        if image is None:
            return None
        rendered = image.resize((self.mapper.canvas_width, self.mapper.canvas_height))
        rendered = self._apply_graphic_effects(rendered, stage.get("effects", {}))
        tk_image = self._image_tk.PhotoImage(rendered)
        self._tk_image_cache[cache_key] = tk_image
        return tk_image

    def _drawable_tk_image(self, drawable: dict[str, Any]) -> Any | None:
        cache_key, rendered = self._drawable_rendered_image(drawable)
        if cache_key is None or rendered is None:
            return None
        cached = self._tk_image_cache.get(cache_key)
        if cached is not None:
            return cached
        tk_image = self._image_tk.PhotoImage(rendered)
        self._tk_image_cache[cache_key] = tk_image
        return tk_image

    def _drawable_rendered_image(self, drawable: dict[str, Any]) -> tuple[tuple[Any, ...] | None, Any | None]:
        costume = drawable.get("costume", {})
        image = self.asset_store.load_image(costume)
        if image is None:
            return (None, None)
        cache_key = self._drawable_cache_key(drawable, image)
        cached = self._rendered_image_cache.get(cache_key)
        if cached is not None:
            return (cache_key, cached)
        rendered = self._transform_drawable_image(image, drawable)
        self._rendered_image_cache[cache_key] = rendered
        return (cache_key, rendered)

    def _drawable_cache_key(self, drawable: dict[str, Any], image: Any) -> tuple[Any, ...]:
        width, height = self._scaled_drawable_dimensions(image, drawable)
        rotation_key = self._drawable_rotation_key(drawable)
        return (
            "drawable",
            drawable["costume"].get("md5ext"),
            width,
            height,
            *rotation_key,
            self._effects_cache_key(drawable.get("effects", {})),
        )

    def _scaled_drawable_dimensions(self, image: Any, drawable: dict[str, Any]) -> tuple[int, int]:
        size_scale = max(0.0, drawable["size"] / 100.0)
        width = max(1, int(image.width * size_scale * self.scale))
        height = max(1, int(image.height * size_scale * self.scale))
        return (width, height)

    def _drawable_rotation_key(self, drawable: dict[str, Any]) -> tuple[Any, ...]:
        rotation_style = str(drawable["rotation_style"]).strip().lower()
        direction = float(drawable["direction"])
        if rotation_style == "left-right":
            return ("left-right", direction < 0)
        if rotation_style == "don't rotate":
            return ("fixed",)
        angle = (90.0 - direction) % 360.0
        if angle == 0.0:
            return ("fixed",)
        return ("rotated", round(angle, 6))

    def _transform_drawable_image(self, image: Any, drawable: dict[str, Any]) -> Any:
        from PIL import ImageOps

        width, height = self._scaled_drawable_dimensions(image, drawable)
        rendered = image.resize((width, height))

        rotation_style = str(drawable["rotation_style"]).strip().lower()
        direction = float(drawable["direction"])
        if rotation_style == "left-right":
            if direction < 0:
                rendered = ImageOps.mirror(rendered)
            return self._apply_graphic_effects(rendered, drawable.get("effects", {}))
        if rotation_style == "don't rotate":
            return self._apply_graphic_effects(rendered, drawable.get("effects", {}))

        angle = (90.0 - direction) % 360.0
        if angle == 0:
            return self._apply_graphic_effects(rendered, drawable.get("effects", {}))
        return self._apply_graphic_effects(rendered.rotate(angle, expand=True), drawable.get("effects", {}))

    def _effects_cache_key(self, effects: dict[str, Any]) -> tuple[tuple[str, float], ...]:
        normalized: list[tuple[str, float]] = []
        for name, raw in sorted(effects.items()):
            value = self._effect_number(raw)
            if value != 0.0:
                normalized.append((str(name), round(value, 6)))
        return tuple(normalized)

    def _effect_number(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _apply_graphic_effects(self, image: Any, effects: dict[str, Any]) -> Any:
        if not effects:
            return image
        rendered = image.convert("RGBA")
        if self._effect_number(effects.get("color")):
            rendered = self._apply_color_effect(rendered, self._effect_number(effects.get("color")))
        if self._effect_number(effects.get("brightness")):
            rendered = self._apply_brightness_effect(rendered, self._effect_number(effects.get("brightness")))
        if self._effect_number(effects.get("pixelate")):
            rendered = self._apply_pixelate_effect(rendered, self._effect_number(effects.get("pixelate")))
        if self._effect_number(effects.get("mosaic")):
            rendered = self._apply_mosaic_effect(rendered, self._effect_number(effects.get("mosaic")))
        if self._effect_number(effects.get("whirl")):
            rendered = self._apply_whirl_effect(rendered, self._effect_number(effects.get("whirl")))
        if self._effect_number(effects.get("fisheye")):
            rendered = self._apply_fisheye_effect(rendered, self._effect_number(effects.get("fisheye")))
        if self._effect_number(effects.get("ghost")):
            rendered = self._apply_ghost_effect(rendered, self._effect_number(effects.get("ghost")))
        return rendered

    def _apply_color_effect(self, image: Any, value: float) -> Any:
        from PIL import Image

        alpha = image.getchannel("A")
        hsv = image.convert("RGB").convert("HSV")
        channels = list(hsv.split())
        hue_shift = int(round((value / 200.0) * 255.0)) % 256
        channels[0] = channels[0].point(lambda pixel: (pixel + hue_shift) % 256)
        colored = Image.merge("HSV", channels).convert("RGBA")
        colored.putalpha(alpha)
        return colored

    def _apply_brightness_effect(self, image: Any, value: float) -> Any:
        from PIL import Image

        red, green, blue, alpha = image.split()
        if value >= 0:
            factor = min(value, 100.0) / 100.0

            def brighten(pixel: int) -> int:
                return max(0, min(255, int(round(pixel + (255 - pixel) * factor))))

            return Image.merge("RGBA", (red.point(brighten), green.point(brighten), blue.point(brighten), alpha))

        factor = max(0.0, 1.0 + max(value, -100.0) / 100.0)

        def darken(pixel: int) -> int:
            return max(0, min(255, int(round(pixel * factor))))

        return Image.merge("RGBA", (red.point(darken), green.point(darken), blue.point(darken), alpha))

    def _apply_ghost_effect(self, image: Any, value: float) -> Any:
        from PIL import Image

        ghost_factor = max(0.0, 1.0 - min(max(value, 0.0), 100.0) / 100.0)
        red, green, blue, alpha = image.split()
        alpha = alpha.point(lambda pixel: max(0, min(255, int(round(pixel * ghost_factor)))))
        return Image.merge("RGBA", (red, green, blue, alpha))

    def _apply_pixelate_effect(self, image: Any, value: float) -> Any:
        from PIL import Image

        block = max(1, int(abs(value) / 10.0) + 1)
        width = max(1, image.width // block)
        height = max(1, image.height // block)
        resampling = getattr(Image, "Resampling", Image)
        return image.resize((width, height), resampling.BOX).resize((image.width, image.height), resampling.NEAREST)

    def _apply_mosaic_effect(self, image: Any, value: float) -> Any:
        from PIL import Image

        cells = max(1, int(abs(value) / 10.0) + 1)
        tile_width = max(1, image.width // cells)
        tile_height = max(1, image.height // cells)
        resampling = getattr(Image, "Resampling", Image)
        tile = image.resize((tile_width, tile_height), resampling.BOX)
        mosaic = Image.new("RGBA", image.size, (0, 0, 0, 0))
        for x in range(0, image.width, tile_width):
            for y in range(0, image.height, tile_height):
                mosaic.alpha_composite(tile, (x, y))
        return mosaic

    def _apply_whirl_effect(self, image: Any, value: float) -> Any:
        return self._warp_image(image, lambda dx, dy, radius: self._whirl_source_offset(dx, dy, radius, value))

    def _apply_fisheye_effect(self, image: Any, value: float) -> Any:
        return self._warp_image(image, lambda dx, dy, radius: self._fisheye_source_offset(dx, dy, radius, value))

    def _warp_image(self, image: Any, mapper: Any) -> Any:
        from PIL import Image

        source = image.convert("RGBA")
        warped = Image.new("RGBA", source.size, (0, 0, 0, 0))
        src_pixels = source.load()
        dst_pixels = warped.load()
        center_x = (source.width - 1) / 2.0
        center_y = (source.height - 1) / 2.0
        max_radius = max(1.0, min(source.width, source.height) / 2.0)
        for y in range(source.height):
            for x in range(source.width):
                dx = x - center_x
                dy = y - center_y
                radius = math.hypot(dx, dy) / max_radius
                source_dx, source_dy = mapper(dx, dy, radius)
                source_x = int(round(center_x + source_dx))
                source_y = int(round(center_y + source_dy))
                if 0 <= source_x < source.width and 0 <= source_y < source.height:
                    dst_pixels[x, y] = src_pixels[source_x, source_y]
        return warped

    def _whirl_source_offset(self, dx: float, dy: float, radius: float, value: float) -> tuple[float, float]:
        if radius >= 1.0:
            return (dx, dy)
        angle = math.radians(value) * (1.0 - radius) ** 2
        cos_angle = math.cos(-angle)
        sin_angle = math.sin(-angle)
        return (dx * cos_angle - dy * sin_angle, dx * sin_angle + dy * cos_angle)

    def _fisheye_source_offset(self, dx: float, dy: float, radius: float, value: float) -> tuple[float, float]:
        if radius <= 0.0 or radius >= 1.0:
            return (dx, dy)
        power = max(0.2, 1.0 + value / 100.0)
        source_radius = radius ** power
        scale = source_radius / radius
        return (dx * scale, dy * scale)

    def _event_key_name(self, event: Any) -> str | None:
        keysym = str(getattr(event, "keysym", "") or getattr(event, "char", "")).strip()
        if not keysym:
            return None
        aliases = {
            "Left": "left arrow",
            "Right": "right arrow",
            "Up": "up arrow",
            "Down": "down arrow",
            "Return": "enter",
            "space": "space",
            "BackSpace": "backspace",
        }
        return aliases.get(keysym, keysym.lower())

    def _sync_mouse(self, event: Any) -> None:
        stage_x, stage_y = self.mapper.to_stage(float(getattr(event, "x", 0.0)), float(getattr(event, "y", 0.0)))
        self.input_provider.set_mouse_position(stage_x, stage_y)

    def _on_key_press(self, event: Any) -> None:
        if getattr(event, "widget", None) is self._prompt_entry:
            return
        key_name = self._event_key_name(event)
        if key_name is None:
            return
        self.input_provider.press_key(key_name)

    def _on_key_release(self, event: Any) -> None:
        if getattr(event, "widget", None) is self._prompt_entry:
            return
        key_name = self._event_key_name(event)
        if key_name is None:
            return
        self.input_provider.release_key(key_name)

    def _on_mouse_motion(self, event: Any) -> None:
        self._sync_mouse(event)

    def _on_mouse_press(self, event: Any) -> None:
        self._sync_mouse(event)
        self.input_provider.set_mouse_button(True)
        if self._canvas is not None:
            self._canvas.focus_set()
        instance_id = self._clicked_sprite_instance_id(float(getattr(event, "x", 0.0)), float(getattr(event, "y", 0.0)))
        if instance_id is not None:
            self.vm.emit_sprite_click(instance_id)

    def _on_mouse_release(self, event: Any) -> None:
        self._sync_mouse(event)
        self.input_provider.set_mouse_button(False)

    def _on_mouse_leave(self, event: Any) -> None:
        self.input_provider.set_mouse_button(False)

    def _clicked_sprite_instance_id(self, canvas_x: float, canvas_y: float) -> int | None:
        snapshot = self._last_render_snapshot or self.vm.render_snapshot()
        for drawable in reversed(snapshot.get("drawables", ())):
            if not drawable.get("visible", False):
                continue
            if self._drawable_contains_canvas_point(drawable, canvas_x, canvas_y):
                return int(drawable["instance_id"])
        return None

    def _drawable_contains_canvas_point(self, drawable: dict[str, Any], canvas_x: float, canvas_y: float) -> bool:
        _, rendered = self._drawable_rendered_image(drawable)
        if rendered is None:
            return False
        center_x, center_y = self.mapper.to_canvas(drawable["position"]["x"], drawable["position"]["y"])
        left = center_x - rendered.width / 2
        top = center_y - rendered.height / 2
        local_x = int(canvas_x - left)
        local_y = int(canvas_y - top)
        if local_x < 0 or local_x >= rendered.width or local_y < 0 or local_y >= rendered.height:
            return False
        pixel = rendered.getpixel((local_x, local_y))
        alpha = pixel[3] if isinstance(pixel, tuple) and len(pixel) >= 4 else 255
        return alpha > 0

    def _paint_monitors(self) -> None:
        assert self._canvas is not None
        for monitor in self._visible_variable_monitors():
            text = f"{monitor['label']}: {monitor['value']}"
            x = float(monitor["x"])
            y = float(monitor["y"])
            box_width = max(120.0 * self.scale, 16.0 * self.scale + len(text) * 7.0 * self.scale)
            box_height = 22.0 * self.scale
            self._canvas.create_rectangle(
                x,
                y,
                x + box_width,
                y + box_height,
                fill="#fff7d6",
                outline="#c2410c",
                width=max(1, int(self.scale)),
            )
            self._canvas.create_text(
                x + 8.0 * self.scale,
                y + box_height / 2,
                text=text,
                anchor="w",
                fill="#111827",
            )

    def _visible_variable_monitors(self) -> list[dict[str, Any]]:
        monitors: list[dict[str, Any]] = []
        fallback_row = 0
        for monitor in self.project.monitors:
            if str(monitor.get("opcode", "")).strip() != "data_variable":
                continue
            if not bool(monitor.get("visible", False)):
                continue
            variable_name = str((monitor.get("params") or {}).get("VARIABLE") or "").strip()
            if not variable_name:
                continue
            sprite_name = monitor.get("spriteName")
            label = str(monitor.get("label") or variable_name)
            x_raw = monitor.get("x")
            y_raw = monitor.get("y")
            if isinstance(x_raw, (int, float)) and isinstance(y_raw, (int, float)):
                x = float(x_raw) * self.scale
                y = float(y_raw) * self.scale
            else:
                x = 8.0 * self.scale
                y = (8.0 + fallback_row * 28.0) * self.scale
                fallback_row += 1
            monitors.append(
                {
                    "label": label,
                    "value": self._monitor_value(variable_name, sprite_name),
                    "x": x,
                    "y": y,
                }
            )
        return monitors

    def _monitor_value(self, variable_name: str, sprite_name: Any) -> Any:
        if isinstance(sprite_name, str) and sprite_name in self.vm.state.original_instance_ids:
            instance_id = self.vm.state.get_original_instance_id(sprite_name)
            instance = self.vm.state.get_instance(instance_id)
            if variable_name in instance.local_variables:
                return instance.local_variables[variable_name]
        return self.vm.state.stage_variables.get(variable_name, 0)

    def _sync_prompt(self, snapshot: dict[str, Any]) -> None:
        prompt = None
        for status in snapshot.get("thread_status", ()):
            if status.get("wait_state") == "answer":
                prompt = status.get("wait_detail") or ""
                break
        if prompt:
            if not self._prompt_visible and self._prompt_frame is not None:
                self._prompt_frame.pack(fill="x", padx=8, pady=8)
                self._prompt_visible = True
            if self._prompt_label is not None:
                self._prompt_label.config(text=prompt)
            if self._prompt_entry is not None and self._prompt_entry.focus_get() is None:
                self._prompt_entry.focus_set()
            return
        if self._prompt_visible and self._prompt_frame is not None:
            self._prompt_frame.pack_forget()
            self._prompt_visible = False

    def _submit_answer(self, event: Any = None) -> str | None:
        if self._prompt_entry is None:
            return None
        value = self._prompt_entry.get()
        self._prompt_entry.delete(0, "end")
        self.input_provider.queue_answer(value)
        info(_LOGGER, "render.MinimalRenderer._submit_answer", "submitted display answer len=%d", len(value))
        if self._canvas is not None:
            self._canvas.focus_set()
        return "break"
