from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from sb3vm.cli import build_parser, cmd_run_display
from sb3vm.io.load_sb3 import load_sb3
from sb3vm.model.project import Project
from sb3vm.render import MinimalRenderer, RenderAssetStore, RendererDependencyError, ScratchCoordinateMapper
from sb3vm.vm.input_provider import InteractiveInputProvider
from sb3vm.vm.runtime import Sb3Vm
from tests.test_helpers import write_sb3


def _png_bytes(color: tuple[int, int, int, int]) -> bytes:
    from PIL import Image

    image = Image.new("RGBA", (4, 4), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _masked_png_bytes(size: tuple[int, int], *, opaque_box: tuple[int, int, int, int]) -> bytes:
    from PIL import Image

    image = Image.new("RGBA", size, (0, 0, 0, 0))
    left, top, right, bottom = opaque_box
    for x in range(left, right):
        for y in range(top, bottom):
            image.putpixel((x, y), (0, 255, 0, 255))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_project_json() -> dict:
    return {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": {},
                "comments": {},
                "costumes": [{"name": "backdrop1", "assetId": "bg", "md5ext": "bg.png"}],
                "sounds": [],
            },
            {
                "isStage": False,
                "name": "Sprite1",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": {},
                "comments": {},
                "costumes": [{"name": "costume1", "assetId": "sprite", "md5ext": "sprite.png"}],
                "sounds": [],
                "x": 0,
                "y": 0,
                "visible": True,
                "currentCostume": 0,
            },
        ],
        "monitors": [],
        "extensions": [],
        "meta": {"semver": "3.0.0"},
    }


def test_coordinate_mapper_uses_scratch_stage_space() -> None:
    mapper = ScratchCoordinateMapper(scale=2.0)

    assert mapper.canvas_width == 960
    assert mapper.canvas_height == 720
    assert mapper.to_canvas(0, 0) == (480.0, 360.0)
    assert mapper.to_canvas(-240, 180) == (0.0, 0.0)
    assert mapper.to_canvas(240, -180) == (960.0, 720.0)
    assert mapper.to_stage(480, 360) == (0.0, 0.0)
    assert mapper.to_stage(0, 0) == (-240.0, 180.0)


def test_asset_store_loads_and_caches_png_assets(tmp_path: Path) -> None:
    path = tmp_path / "render.sb3"
    write_sb3(
        path,
        _render_project_json(),
        assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))},
    )
    project = load_sb3(path)
    store = RenderAssetStore(project)
    reference = {
        "target_name": "Sprite1",
        "index": 0,
        "count": 1,
        "name": "costume1",
        "asset_id": "sprite",
        "md5ext": "sprite.png",
    }

    first = store.load_image(reference)
    second = store.load_image(reference)

    assert first is not None
    assert first is second
    assert first.size == (4, 4)


def test_asset_store_svg_requires_optional_dependency_when_missing() -> None:
    project = Project.from_json(
        {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {},
                    "comments": {},
                    "costumes": [{"name": "backdrop1", "assetId": "bg", "md5ext": "bg.svg"}],
                    "sounds": [],
                }
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0"},
        },
        assets={"bg.svg": b"<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'></svg>"},
    )
    store = RenderAssetStore(project)
    reference = {
        "target_name": "Stage",
        "index": 0,
        "count": 1,
        "name": "backdrop1",
        "asset_id": "bg",
        "md5ext": "bg.svg",
    }

    try:
        image = store.load_image(reference)
    except RendererDependencyError:
        image = None

    if image is None:
        with pytest.raises(RendererDependencyError):
            store._rasterize_svg(b"<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'></svg>")
    else:
        assert image.size[0] > 0
        assert image.size[1] > 0


def test_run_display_cli_wires_renderer_without_debug_snapshot(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    parser = build_parser()
    args = parser.parse_args(["run-display", str(path), "--seconds", "0", "--fps", "12", "--scale", "1.5", "--monitors"])
    seen: dict[str, object] = {}

    def fake_run(self: MinimalRenderer, *, seconds: float | None = None, dt: float = 1 / 30) -> None:
        seen["seconds"] = seconds
        seen["dt"] = dt
        seen["scale"] = self.scale
        seen["fps"] = self.fps
        seen["show_monitors"] = self.show_monitors
        seen["render_snapshot"] = self.vm.render_snapshot()

    monkeypatch.setattr(MinimalRenderer, "run", fake_run)

    assert cmd_run_display(args) == 0
    assert seen["seconds"] == 0.0
    assert seen["fps"] == 12
    assert seen["scale"] == 1.5
    assert seen["show_monitors"] is True
    assert "drawables" in seen["render_snapshot"]


def test_run_display_cli_uses_interactive_input_provider(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    parser = build_parser()
    args = parser.parse_args(["run-display", str(path), "--seconds", "0"])
    seen: dict[str, object] = {}

    def fake_run(self: MinimalRenderer, *, seconds: float | None = None, dt: float = 1 / 30) -> None:
        seen["provider"] = self.vm.input_provider

    monkeypatch.setattr(MinimalRenderer, "run", fake_run)

    assert cmd_run_display(args) == 0
    assert isinstance(seen["provider"], InteractiveInputProvider)


class _FakeEvent:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class _FakeEntry:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.focused = False

    def get(self) -> str:
        return self.value

    def delete(self, start: int, end: str) -> None:
        self.value = ""

    def focus_set(self) -> None:
        self.focused = True

    def focus_get(self):
        return None


class _FakeCanvas:
    def __init__(self) -> None:
        self.focused = False
        self.bindings: dict[str, object] = {}
        self.drawn_text: list[dict[str, object]] = []
        self.drawn_rectangles: list[tuple[float, float, float, float]] = []
        self.drawn_images: list[dict[str, object]] = []

    def focus_set(self) -> None:
        self.focused = True

    def bind(self, event_name: str, handler) -> None:
        self.bindings[event_name] = handler

    def delete(self, tag: str) -> None:
        self.drawn_text.clear()
        self.drawn_rectangles.clear()
        self.drawn_images.clear()

    def create_image(self, x: float, y: float, **kwargs) -> None:
        self.drawn_images.append({"x": x, "y": y, **kwargs})

    def create_rectangle(self, x1: float, y1: float, x2: float, y2: float, **kwargs) -> None:
        self.drawn_rectangles.append((x1, y1, x2, y2))

    def create_text(self, x: float, y: float, **kwargs) -> None:
        self.drawn_text.append({"x": x, "y": y, **kwargs})


class _FakeImageTk:
    def __init__(self) -> None:
        self.calls = 0

    def PhotoImage(self, image):
        self.calls += 1
        return {"image": image, "call": self.calls}


def test_renderer_event_handlers_update_interactive_state(tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))

    renderer._on_key_press(_FakeEvent(keysym="Left", widget=None))
    renderer._on_mouse_motion(_FakeEvent(x=240, y=180))
    renderer._on_mouse_press(_FakeEvent(x=480, y=360))
    renderer._on_mouse_release(_FakeEvent(x=480, y=360))
    renderer._on_key_release(_FakeEvent(keysym="Left", widget=None))

    provider = renderer.input_provider
    assert isinstance(provider, InteractiveInputProvider)
    assert provider.key_pressed("left arrow") is False
    assert provider.mouse_x() == 240.0
    assert provider.mouse_y() == -180.0
    assert provider.mouse_down() is False


def test_renderer_submit_answer_queues_input(tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))
    renderer._prompt_entry = _FakeEntry("Ada")
    renderer._canvas = _FakeCanvas()

    assert renderer._submit_answer() == "break"
    assert renderer.input_provider.pop_answer() == "Ada"
    assert renderer._canvas.focused is True


def test_renderer_transforms_drawable_for_rotation_and_flip(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))

    base = Image.new("RGBA", (10, 4), (0, 255, 0, 255))

    rotated = renderer._transform_drawable_image(
        base,
        {
            "size": 100.0,
            "rotation_style": "all around",
            "direction": 0.0,
        },
    )
    flipped = renderer._transform_drawable_image(
        base,
        {
            "size": 100.0,
            "rotation_style": "left-right",
            "direction": -90.0,
        },
    )
    fixed = renderer._transform_drawable_image(
        base,
        {
            "size": 100.0,
            "rotation_style": "don't rotate",
            "direction": 0.0,
        },
    )

    assert rotated.size == (4, 10)
    assert flipped.size == (10, 4)
    assert fixed.size == (10, 4)


def test_renderer_caches_identical_drawable_images(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))
    renderer._image_tk = _FakeImageTk()
    drawable = {
        "costume": {
            "target_name": "Sprite1",
            "index": 0,
            "count": 1,
            "name": "costume1",
            "asset_id": "sprite",
            "md5ext": "sprite.png",
        },
        "size": 100.0,
        "rotation_style": "all around",
        "direction": 90.0,
    }
    call_count = 0
    original = renderer._transform_drawable_image

    def wrapped(image, payload):
        nonlocal call_count
        call_count += 1
        return original(image, payload)

    monkeypatch.setattr(renderer, "_transform_drawable_image", wrapped)

    first = renderer._drawable_tk_image(drawable)
    second = renderer._drawable_tk_image(dict(drawable))

    assert first is second
    assert call_count == 1
    assert renderer._image_tk.calls == 1


def test_renderer_invalidates_drawable_cache_when_rotation_changes(tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))
    renderer._image_tk = _FakeImageTk()
    drawable = {
        "costume": {
            "target_name": "Sprite1",
            "index": 0,
            "count": 1,
            "name": "costume1",
            "asset_id": "sprite",
            "md5ext": "sprite.png",
        },
        "size": 100.0,
        "rotation_style": "all around",
        "direction": 90.0,
    }

    first = renderer._drawable_tk_image(drawable)
    rotated = renderer._drawable_tk_image({**drawable, "direction": 0.0})

    assert first is not rotated
    assert renderer._image_tk.calls == 2


def test_renderer_applies_graphic_effects_to_drawables(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((100, 50, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))
    base = Image.new("RGBA", (6, 6), (100, 50, 0, 255))

    effected = renderer._transform_drawable_image(
        base,
        {
            "size": 100.0,
            "rotation_style": "don't rotate",
            "direction": 90.0,
            "effects": {
                "ghost": 50.0,
                "brightness": 100.0,
            },
        },
    )

    assert effected.getpixel((0, 0))[3] < 255
    assert effected.getpixel((0, 0))[0] > 100


def test_renderer_cache_invalidates_when_effects_change(tmp_path: Path) -> None:
    path = tmp_path / "display.sb3"
    write_sb3(path, _render_project_json(), assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))
    renderer._image_tk = _FakeImageTk()
    drawable = {
        "costume": {
            "target_name": "Sprite1",
            "index": 0,
            "count": 1,
            "name": "costume1",
            "asset_id": "sprite",
            "md5ext": "sprite.png",
        },
        "size": 100.0,
        "rotation_style": "all around",
        "direction": 90.0,
        "effects": {},
    }

    first = renderer._drawable_tk_image(drawable)
    ghosted = renderer._drawable_tk_image({**drawable, "effects": {"ghost": 40.0}})

    assert first is not ghosted
    assert renderer._image_tk.calls == 2


def test_renderer_click_hit_testing_uses_sprite_alpha_mask(monkeypatch, tmp_path: Path) -> None:
    project_json = _render_project_json()
    path = tmp_path / "display.sb3"
    write_sb3(
        path,
        project_json,
        assets={
            "bg.png": _png_bytes((255, 0, 0, 255)),
            "sprite.png": _masked_png_bytes((20, 20), opaque_box=(5, 5, 15, 15)),
        },
    )
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project))
    renderer._canvas = _FakeCanvas()
    renderer._last_render_snapshot = renderer.vm.render_snapshot()
    clicked: list[int] = []

    monkeypatch.setattr(renderer.vm, "emit_sprite_click", lambda instance_id: clicked.append(instance_id) or set())

    renderer._on_mouse_press(_FakeEvent(x=231, y=171))
    renderer._on_mouse_press(_FakeEvent(x=240, y=180))

    assert len(clicked) == 1
    assert clicked[0] == renderer.vm.state.get_original_instance_id("Sprite1")


def test_renderer_paints_visible_variable_monitors(tmp_path: Path) -> None:
    project_json = _render_project_json()
    project_json["targets"][0]["variables"] = {"v1": ["score", 7]}
    project_json["monitors"] = [
        {
            "id": "score-monitor",
            "opcode": "data_variable",
            "params": {"VARIABLE": "score"},
            "visible": True,
            "x": 12,
            "y": 16,
        },
        {
            "id": "hidden-score-monitor",
            "opcode": "data_variable",
            "params": {"VARIABLE": "score"},
            "visible": False,
        },
    ]
    path = tmp_path / "display.sb3"
    write_sb3(path, project_json, assets={"bg.png": _png_bytes((255, 0, 0, 255)), "sprite.png": _png_bytes((0, 255, 0, 255))})
    project = load_sb3(path)
    renderer = MinimalRenderer(project, Sb3Vm(project), show_monitors=True)
    renderer._canvas = _FakeCanvas()

    renderer._paint_monitors()

    assert len(renderer._canvas.drawn_rectangles) == 1
    assert len(renderer._canvas.drawn_text) == 1
    assert renderer._canvas.drawn_text[0]["text"] == "score: 7"
