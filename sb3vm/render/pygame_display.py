"""Pygame-based renderer (SDL2 backend).

Significantly faster than :class:`~sb3vm.render.display.MinimalRenderer`
(Tkinter) because:

* Sprite surfaces are blitted via SDL2 hardware acceleration rather than
  uploaded as Tkinter ``PhotoImage`` objects each frame.
* ``pygame.image.fromstring`` converts a PIL RGBA image to a surface in one
  C-level call; there is no per-pixel Python loop.
* The event loop is a tight ``while`` with no Tcl/Tk overhead.

PIL remains the image-transform back-end (resize, rotate, graphic effects)
because those results are already cached between frames.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from sb3vm.log import debug, get_logger, info
from sb3vm.model.project import Project
from sb3vm.render.assets import RenderAssetStore, RendererDependencyError, RendererError
from sb3vm.render.compositor import Compositor
from sb3vm.render.effects import apply_graphic_effects
from sb3vm.render.pen import PenLayer
from sb3vm.render.display import ScratchCoordinateMapper
from sb3vm.vm.input_provider import HeadlessInputProvider, InteractiveInputProvider
from sb3vm.vm.runtime import Sb3Vm


_LOGGER = get_logger(__name__)

# Scratch key names indexed by pygame key constant (populated once on first use)
_KEY_MAP: dict[int, str] | None = None


def _get_key_map() -> dict[int, str]:
    global _KEY_MAP
    if _KEY_MAP is not None:
        return _KEY_MAP
    import pygame
    _KEY_MAP = {
        pygame.K_LEFT: "left arrow",
        pygame.K_RIGHT: "right arrow",
        pygame.K_UP: "up arrow",
        pygame.K_DOWN: "down arrow",
        pygame.K_RETURN: "enter",
        pygame.K_KP_ENTER: "enter",
        pygame.K_SPACE: "space",
        pygame.K_BACKSPACE: "backspace",
        pygame.K_DELETE: "delete",
    }
    return _KEY_MAP


@dataclass
class PygameRenderer:
    """SDL2-backed renderer for sb3vm projects.

    Drop-in replacement for :class:`~sb3vm.render.display.MinimalRenderer`
    with a significantly faster blit pipeline.

    Parameters
    ----------
    project:
        The loaded Scratch project.
    vm:
        A configured (but not yet started) :class:`~sb3vm.vm.runtime.Sb3Vm`.
    scale:
        Display scale factor (1.0 → 480 × 360 window).
    fps:
        Target frames per second for the game loop.
    show_monitors:
        Whether to draw variable monitor overlays.
    """

    project: Project
    vm: Sb3Vm
    scale: float = 1.0
    fps: int = 30
    show_monitors: bool = False
    asset_store: RenderAssetStore = field(init=False)

    def __post_init__(self) -> None:
        self.asset_store = RenderAssetStore(self.project)
        self.mapper = ScratchCoordinateMapper(scale=self.scale)
        cw = self.mapper.canvas_width
        ch = self.mapper.canvas_height

        self._pen_layer = PenLayer(cw, ch)
        self.vm.pen_clear_hook = self._pen_clear
        self.vm.pen_stamp_hook = self._pen_stamp
        self.vm.pen_draw_hook = self._pen_draw

        compositor = Compositor(self.asset_store, scale=self.scale)
        self.vm.compositor = compositor

        # PIL rendered-image cache (costume md5ext + transforms → PIL Image)
        self._rendered_image_cache: dict[tuple[Any, ...], Any] = {}
        # pygame Surface cache (same keys as rendered-image cache → pygame.Surface)
        self._surface_cache: dict[tuple[Any, ...], Any] = {}

        self._last_snapshot: dict[str, Any] | None = None
        self._started = False

        # Prompt (ask block) state
        self._prompt_active = False
        self._prompt_text = ""
        self._prompt_question = ""

        self.input_provider = self._ensure_interactive_input_provider()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, *, seconds: float | None = None, dt: float = 1 / 30) -> None:
        """Open a pygame window and run the VM.

        Parameters
        ----------
        seconds:
            Stop after this many simulated seconds (``None`` = run until
            the window is closed).
        dt:
            Simulation time-step in seconds.
        """
        try:
            import pygame
        except ModuleNotFoundError as exc:
            raise RendererDependencyError(
                "PygameRenderer requires pygame. "
                "Install with `pip install 'sb3vm[render]'`."
            ) from exc

        try:
            pygame.init()
            pygame.font.init()
        except Exception as exc:
            raise RendererError(f"pygame.init() failed: {exc}") from exc

        cw, ch = self.mapper.canvas_width, self.mapper.canvas_height
        try:
            screen = pygame.display.set_mode((cw, ch))
        except Exception as exc:
            raise RendererError(f"Unable to open pygame display: {exc}") from exc

        pygame.display.set_caption("sb3vm")
        clock = pygame.time.Clock()
        font_sm = pygame.font.SysFont("sans-serif", max(10, int(12 * self.scale)))
        font_md = pygame.font.SysFont("sans-serif", max(12, int(14 * self.scale)))

        key_map = _get_key_map()
        self._maybe_start_vm()

        # Initial paint before entering the loop
        snapshot = self.vm.render_snapshot()
        self._last_snapshot = snapshot
        self._paint(screen, snapshot, font_sm, font_md)
        pygame.display.flip()

        elapsed = 0.0
        running = True

        while running:
            # ---- event handling ----
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if self._prompt_active:
                        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.input_provider.queue_answer(self._prompt_text)
                            self._prompt_active = False
                            self._prompt_text = ""
                            pygame.key.stop_text_input()
                        elif event.key == pygame.K_BACKSPACE:
                            self._prompt_text = self._prompt_text[:-1]
                    else:
                        name = key_map.get(event.key) or (pygame.key.name(event.key) or "").lower()
                        if name:
                            self.input_provider.press_key(name)

                elif event.type == pygame.KEYUP:
                    if not self._prompt_active:
                        name = key_map.get(event.key) or (pygame.key.name(event.key) or "").lower()
                        if name:
                            self.input_provider.release_key(name)

                elif event.type == pygame.TEXTINPUT:
                    if self._prompt_active:
                        self._prompt_text += event.text

                elif event.type == pygame.MOUSEMOTION:
                    sx, sy = self.mapper.to_stage(float(event.pos[0]), float(event.pos[1]))
                    self.input_provider.set_mouse_position(sx, sy)

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    sx, sy = self.mapper.to_stage(float(event.pos[0]), float(event.pos[1]))
                    self.input_provider.set_mouse_position(sx, sy)
                    self.input_provider.set_mouse_button(True)
                    iid = self._clicked_sprite(float(event.pos[0]), float(event.pos[1]))
                    if iid is not None:
                        self.vm.emit_sprite_click(iid)

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    sx, sy = self.mapper.to_stage(float(event.pos[0]), float(event.pos[1]))
                    self.input_provider.set_mouse_position(sx, sy)
                    self.input_provider.set_mouse_button(False)

            # ---- VM step ----
            if seconds is None or elapsed < seconds:
                self.vm.step(dt)
                elapsed += dt

            if seconds is not None and elapsed >= seconds:
                running = False
                break

            # ---- render ----
            snapshot = self.vm.render_snapshot()
            self._last_snapshot = snapshot
            self._sync_prompt(snapshot)
            self._paint(screen, snapshot, font_sm, font_md)
            pygame.display.flip()
            clock.tick(self.fps)

        pygame.quit()

    # ------------------------------------------------------------------
    # Paint pipeline
    # ------------------------------------------------------------------

    def _paint(
        self,
        screen: Any,
        snapshot: dict[str, Any],
        font_sm: Any,
        font_md: Any,
    ) -> None:
        screen.fill((255, 255, 255))
        self._blit_stage(screen, snapshot.get("stage", {}))
        self._blit_pen_layer(screen)
        for drawable in snapshot.get("drawables", []):
            self._blit_drawable(screen, drawable)
        self._draw_speech_bubbles(screen, snapshot.get("drawables", []), font_md)
        if self.show_monitors:
            self._draw_monitors(screen, font_sm)
        if self._prompt_active:
            self._draw_prompt(screen, font_md)

    def _blit_stage(self, screen: Any, stage: dict[str, Any]) -> None:
        backdrop = stage.get("backdrop", {})
        effects = stage.get("effects", {})
        cw, ch = self.mapper.canvas_width, self.mapper.canvas_height
        cache_key = ("stage", backdrop.get("md5ext"), cw, ch, self._effects_key(effects))

        surf = self._surface_cache.get(cache_key)
        if surf is None:
            image = self.asset_store.load_image(backdrop)
            if image is None:
                return
            rendered = apply_graphic_effects(image.resize((cw, ch)), effects)
            surf = self._pil_to_surface(rendered)
            self._surface_cache[cache_key] = surf

        screen.blit(surf, (0, 0))

    def _blit_pen_layer(self, screen: Any) -> None:
        pen_img = self._pen_layer.get_image()
        if pen_img is None:
            return
        # Pen layer changes every draw call, so we don't cache its surface
        screen.blit(self._pil_to_surface(pen_img), (0, 0))

    def _blit_drawable(self, screen: Any, drawable: dict[str, Any]) -> None:
        if not drawable.get("visible", False):
            return
        cache_key, rendered = self._drawable_rendered_image(drawable)
        if cache_key is None or rendered is None:
            return

        surf = self._surface_cache.get(cache_key)
        if surf is None:
            surf = self._pil_to_surface(rendered)
            self._surface_cache[cache_key] = surf

        cx, cy = self.mapper.to_canvas(
            drawable["position"]["x"], drawable["position"]["y"]
        )
        ox, oy = self._rotation_center_offset(rendered, drawable)
        x = int(round(cx - ox - surf.get_width() / 2))
        y = int(round(cy - oy - surf.get_height() / 2))
        screen.blit(surf, (x, y))

    # ------------------------------------------------------------------
    # Speech bubbles (rendered with pygame.draw)
    # ------------------------------------------------------------------

    def _draw_speech_bubbles(
        self, screen: Any, drawables: list[dict[str, Any]], font: Any
    ) -> None:
        for drawable in drawables:
            if not drawable.get("visible", False):
                continue
            dialogue = drawable.get("dialogue")
            if not dialogue or not dialogue.get("text"):
                continue
            text = str(dialogue["text"])
            style = str(dialogue.get("style", "say")).lower()
            cx, cy = self.mapper.to_canvas(
                drawable["position"]["x"], drawable["position"]["y"]
            )
            self._draw_bubble(screen, font, text, style, cx, cy)

    def _draw_bubble(
        self,
        screen: Any,
        font: Any,
        text: str,
        style: str,
        anchor_x: float,
        anchor_y: float,
    ) -> None:
        import pygame

        lines = self._wrap_text(font, text, max_width=200)
        if not lines:
            return

        line_h = font.get_height() + 2
        pad = 8
        box_w = max(font.size(ln)[0] for ln in lines) + pad * 2
        box_h = len(lines) * line_h + pad * 2

        bx = int(anchor_x) + 10
        by = int(anchor_y) - box_h - 20
        cw = self.mapper.canvas_width
        bx = max(2, min(bx, cw - box_w - 2))
        by = max(2, by)

        bg = (255, 255, 255)
        border = (85, 85, 85)

        # Bubble body (rounded rect via border_radius)
        pygame.draw.rect(screen, bg, (bx, by, box_w, box_h), border_radius=8)
        pygame.draw.rect(screen, border, (bx, by, box_w, box_h), width=2, border_radius=8)

        # Tail / thought dots
        tail_x = bx + box_w // 4
        if style == "think":
            for i, r in enumerate([4, 3, 2]):
                cx_dot = tail_x - i * (r * 2 + 3)
                cy_dot = by + box_h + 5 + i * 5
                pygame.draw.circle(screen, bg, (cx_dot, cy_dot), r)
                pygame.draw.circle(screen, border, (cx_dot, cy_dot), r, 1)
        else:
            pts = [
                (tail_x, by + box_h),
                (tail_x + 10, by + box_h),
                (tail_x + 5, by + box_h + 12),
            ]
            pygame.draw.polygon(screen, bg, pts)
            pygame.draw.polygon(screen, border, pts, 2)

        # Text lines
        for i, line in enumerate(lines):
            surf = font.render(line, True, (0, 0, 0))
            screen.blit(surf, (bx + pad, by + pad + i * line_h))

    @staticmethod
    def _wrap_text(font: Any, text: str, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # ------------------------------------------------------------------
    # Monitor overlays
    # ------------------------------------------------------------------

    def _draw_monitors(self, screen: Any, font: Any) -> None:
        import pygame

        for monitor in self._visible_monitors():
            text = f"{monitor['label']}: {monitor['value']}"
            x = int(float(monitor["x"]))
            y = int(float(monitor["y"]))
            text_surf = font.render(text, True, (17, 24, 39))
            box_w = text_surf.get_width() + 16
            box_h = max(22, text_surf.get_height() + 8)
            pygame.draw.rect(screen, (255, 247, 214), (x, y, box_w, box_h), border_radius=3)
            pygame.draw.rect(screen, (194, 65, 12), (x, y, box_w, box_h), width=1, border_radius=3)
            screen.blit(text_surf, (x + 8, y + (box_h - text_surf.get_height()) // 2))

    def _visible_monitors(self) -> list[dict[str, Any]]:
        monitors: list[dict[str, Any]] = []
        fallback_row = 0
        for monitor in self.project.monitors:
            if str(monitor.get("opcode", "")).strip() != "data_variable":
                continue
            if not bool(monitor.get("visible", False)):
                continue
            variable_name = str(
                (monitor.get("params") or {}).get("VARIABLE") or ""
            ).strip()
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

    # ------------------------------------------------------------------
    # Prompt (ask block) UI
    # ------------------------------------------------------------------

    def _sync_prompt(self, snapshot: dict[str, Any]) -> None:
        """Detect whether a thread is waiting for a user answer."""
        import pygame

        question: str | None = None
        for status in snapshot.get("thread_status", ()):
            if status.get("wait_state") == "answer":
                question = str(status.get("wait_detail") or "")
                break

        if question is not None and not self._prompt_active:
            self._prompt_active = True
            self._prompt_question = question
            self._prompt_text = ""
            pygame.key.start_text_input()
        elif question is None and self._prompt_active:
            self._prompt_active = False
            pygame.key.stop_text_input()

    def _draw_prompt(self, screen: Any, font: Any) -> None:
        import pygame

        cw, ch = self.mapper.canvas_width, self.mapper.canvas_height
        bar_h = 36
        bar_y = ch - bar_h

        # Background bar
        pygame.draw.rect(screen, (235, 235, 235), (0, bar_y, cw, bar_h))
        pygame.draw.line(screen, (200, 200, 200), (0, bar_y), (cw, bar_y))

        # Question label
        q_surf = font.render(self._prompt_question, True, (60, 60, 60))
        screen.blit(q_surf, (8, bar_y + (bar_h - q_surf.get_height()) // 2))
        q_w = q_surf.get_width() + 16

        # Text input box
        inp_x = q_w
        inp_w = cw - q_w - 8
        inp_rect = (inp_x, bar_y + 4, inp_w, bar_h - 8)
        pygame.draw.rect(screen, (255, 255, 255), inp_rect, border_radius=4)
        pygame.draw.rect(screen, (100, 100, 200), inp_rect, width=2, border_radius=4)
        t_surf = font.render(self._prompt_text + "|", True, (0, 0, 0))
        screen.blit(t_surf, (inp_x + 6, bar_y + (bar_h - t_surf.get_height()) // 2))

    # ------------------------------------------------------------------
    # Image helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pil_to_surface(img: Any) -> Any:
        """Convert a PIL RGBA image to a ``pygame.Surface`` with per-pixel alpha.

        Uses ``pygame.image.fromstring`` — a single C-level call that is
        significantly faster than constructing a ``PhotoImage`` each frame.
        ``convert_alpha()`` is attempted for display-format optimisation but
        silently skipped in headless/dummy-video environments.
        """
        import pygame

        rgba = img.convert("RGBA") if img.mode != "RGBA" else img
        surf = pygame.image.fromstring(rgba.tobytes(), rgba.size, "RGBA")
        try:
            return surf.convert_alpha()
        except pygame.error:
            return surf

    def _drawable_rendered_image(
        self, drawable: dict[str, Any]
    ) -> tuple[tuple[Any, ...] | None, Any | None]:
        """Return (cache_key, PIL RGBA Image) after applying size/rotation/effects."""
        from PIL import ImageOps

        costume = drawable.get("costume", {})
        image = self.asset_store.load_image(costume)
        if image is None:
            return (None, None)

        size_scale = max(0.0, drawable.get("size", 100.0) / 100.0) * self.scale
        w = max(1, int(image.width * size_scale))
        h = max(1, int(image.height * size_scale))

        rotation_style = str(drawable.get("rotation_style", "all around")).strip().lower()
        direction = float(drawable.get("direction", 90.0))

        if rotation_style == "left-right":
            rot_key: tuple[Any, ...] = ("lr", direction < 0)
        elif rotation_style == "don't rotate":
            rot_key = ("fixed",)
        else:
            angle = round((90.0 - direction) % 360.0, 6)
            rot_key = ("rot", angle)

        effects = drawable.get("effects", {})
        cache_key = (costume.get("md5ext"), w, h, rot_key, self._effects_key(effects))

        cached = self._rendered_image_cache.get(cache_key)
        if cached is not None:
            return (cache_key, cached)

        rendered = image.resize((w, h))
        if rotation_style == "left-right":
            if direction < 0:
                rendered = ImageOps.mirror(rendered)
        elif rotation_style != "don't rotate":
            angle_f = (90.0 - direction) % 360.0
            if angle_f != 0.0:
                rendered = rendered.rotate(angle_f, expand=True)
        rendered = apply_graphic_effects(rendered, effects).convert("RGBA")
        self._rendered_image_cache[cache_key] = rendered
        return (cache_key, rendered)

    def _rotation_center_offset(
        self, rendered: Any, drawable: dict[str, Any]
    ) -> tuple[float, float]:
        """Return (ox, oy): offset from rendered-image centre to rotation pivot."""
        costume = drawable.get("costume", {})
        rc_x = float(costume.get("rotationCenterX") or 0.0)
        rc_y = float(costume.get("rotationCenterY") or 0.0)
        image_ref = self.asset_store.load_image(costume)
        if image_ref is not None:
            native_w, native_h = float(image_ref.width), float(image_ref.height)
        else:
            native_w = float(costume.get("native_width") or rendered.width)
            native_h = float(costume.get("native_height") or rendered.height)
        size_scale = max(0.0, drawable.get("size", 100.0) / 100.0) * self.scale
        ox = (rc_x - native_w / 2) * size_scale
        oy = (rc_y - native_h / 2) * size_scale
        rotation_style = str(drawable.get("rotation_style", "all around")).strip().lower()
        direction = float(drawable.get("direction", 90.0))
        if rotation_style == "don't rotate":
            return (ox, oy)
        if rotation_style == "left-right":
            return (-ox if direction < 0 else ox, oy)
        angle_deg = (90.0 - direction) % 360.0
        if angle_deg == 0.0:
            return (ox, oy)
        a = math.radians(angle_deg)
        return (ox * math.cos(a) - oy * math.sin(a), ox * math.sin(a) + oy * math.cos(a))

    def _clicked_sprite(self, canvas_x: float, canvas_y: float) -> int | None:
        """Return the topmost visible sprite's instance_id at the canvas point."""
        snapshot = self._last_snapshot or self.vm.render_snapshot()
        for drawable in reversed(snapshot.get("drawables", ())):
            if not drawable.get("visible", False):
                continue
            _, rendered = self._drawable_rendered_image(drawable)
            if rendered is None:
                continue
            cx, cy = self.mapper.to_canvas(
                drawable["position"]["x"], drawable["position"]["y"]
            )
            left = cx - rendered.width / 2
            top = cy - rendered.height / 2
            lx = int(canvas_x - left)
            ly = int(canvas_y - top)
            if lx < 0 or lx >= rendered.width or ly < 0 or ly >= rendered.height:
                continue
            pixel = rendered.getpixel((lx, ly))
            alpha = pixel[3] if isinstance(pixel, tuple) and len(pixel) >= 4 else 255
            if alpha > 0:
                return int(drawable["instance_id"])
        return None

    def _effects_key(self, effects: dict[str, Any]) -> tuple[tuple[str, float], ...]:
        return tuple(
            (str(k), round(float(v), 6))
            for k, v in sorted(effects.items())
            if v != 0.0
        )

    # ------------------------------------------------------------------
    # VM helpers
    # ------------------------------------------------------------------

    def _maybe_start_vm(self) -> None:
        if not self._started:
            self.vm.start_green_flag()
            self._started = True

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
        debug(
            _LOGGER,
            "render.PygameRenderer._ensure_interactive_input_provider",
            "attached interactive input provider",
        )
        return interactive

    # ------------------------------------------------------------------
    # Pen hook callbacks (injected into vm)
    # ------------------------------------------------------------------

    def _pen_clear(self) -> None:
        self._pen_layer.clear()
        self._rendered_image_cache.clear()
        self._surface_cache.clear()

    def _pen_stamp(self, instance_id: int) -> None:
        snapshot = self._last_snapshot or self.vm.render_snapshot()
        for drawable in snapshot.get("drawables", []):
            if drawable.get("instance_id") == instance_id:
                _, rendered = self._drawable_rendered_image(drawable)
                if rendered is not None:
                    cx, cy = self.mapper.to_canvas(
                        drawable["position"]["x"], drawable["position"]["y"]
                    )
                    self._pen_layer.stamp_image(rendered, cx, cy)
                break

    def _pen_draw(
        self,
        instance_id: int,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        pen_color: tuple[int, int, int, int],
        pen_size: float,
    ) -> None:
        fx, fy = self.mapper.to_canvas(from_x, from_y)
        tx, ty = self.mapper.to_canvas(to_x, to_y)
        self._pen_layer.draw_line(fx, fy, tx, ty, pen_color, pen_size * self.scale)
