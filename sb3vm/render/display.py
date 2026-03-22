from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sb3vm.model.project import Project
from sb3vm.render.assets import RenderAssetStore, RendererDependencyError, RendererError
from sb3vm.vm.runtime import Sb3Vm
from sb3vm.log import get_logger, instrument_module


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


@dataclass
class MinimalRenderer:
    project: Project
    vm: Sb3Vm
    scale: float = 1.0
    fps: int = 30
    asset_store: RenderAssetStore = field(init=False)

    def __post_init__(self) -> None:
        self.asset_store = RenderAssetStore(self.project)
        self.mapper = ScratchCoordinateMapper(scale=self.scale)
        self._canvas = None
        self._root = None
        self._image_refs: list[Any] = []
        self._started = False

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
        self._maybe_start_vm()
        self._paint(self.vm.render_snapshot())
        if seconds is not None and seconds <= 0:
            self._root.after(0, self._root.destroy)
        else:
            self._schedule_frame(seconds=seconds, dt=dt, elapsed=0.0)
        self._root.mainloop()

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
        self._canvas.delete("all")
        self._image_refs.clear()
        self._paint_stage(snapshot["stage"])
        for drawable in snapshot["drawables"]:
            self._paint_drawable(drawable)

    def _paint_stage(self, stage: dict[str, Any]) -> None:
        assert self._canvas is not None
        backdrop = self.asset_store.load_image(stage["backdrop"])
        if backdrop is None:
            return
        resized = backdrop.resize((self.mapper.canvas_width, self.mapper.canvas_height))
        image = self._image_tk.PhotoImage(resized)
        self._image_refs.append(image)
        self._canvas.create_image(0, 0, image=image, anchor="nw")

    def _paint_drawable(self, drawable: dict[str, Any]) -> None:
        assert self._canvas is not None
        if not drawable["visible"]:
            return
        image = self.asset_store.load_image(drawable["costume"])
        if image is None:
            return
        rendered = self._transform_drawable_image(image, drawable)
        tk_image = self._image_tk.PhotoImage(rendered)
        self._image_refs.append(tk_image)
        x, y = self.mapper.to_canvas(drawable["position"]["x"], drawable["position"]["y"])
        self._canvas.create_image(x, y, image=tk_image, anchor="center")

    def _transform_drawable_image(self, image: Any, drawable: dict[str, Any]) -> Any:
        from PIL import ImageOps

        size_scale = max(0.0, drawable["size"] / 100.0)
        width = max(1, int(image.width * size_scale * self.scale))
        height = max(1, int(image.height * size_scale * self.scale))
        rendered = image.resize((width, height))

        rotation_style = str(drawable["rotation_style"]).strip().lower()
        direction = float(drawable["direction"])
        if rotation_style == "left-right":
            if direction < 0:
                rendered = ImageOps.mirror(rendered)
            return rendered
        if rotation_style == "don't rotate":
            return rendered

        angle = 90.0 - direction
        if angle == 0:
            return rendered
        return rendered.rotate(angle, expand=True)


instrument_module(globals(), _LOGGER)
