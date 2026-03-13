from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from sb3vm.cli import build_parser, cmd_run_display
from sb3vm.io.load_sb3 import load_sb3
from sb3vm.model.project import Project
from sb3vm.render import MinimalRenderer, RenderAssetStore, RendererDependencyError, ScratchCoordinateMapper
from sb3vm.vm.runtime import Sb3Vm
from tests.test_helpers import write_sb3


def _png_bytes(color: tuple[int, int, int, int]) -> bytes:
    from PIL import Image

    image = Image.new("RGBA", (4, 4), color)
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
    args = parser.parse_args(["run-display", str(path), "--seconds", "0", "--fps", "12", "--scale", "1.5"])
    seen: dict[str, object] = {}

    def fake_run(self: MinimalRenderer, *, seconds: float | None = None, dt: float = 1 / 30) -> None:
        seen["seconds"] = seconds
        seen["dt"] = dt
        seen["scale"] = self.scale
        seen["fps"] = self.fps
        seen["render_snapshot"] = self.vm.render_snapshot()

    monkeypatch.setattr(MinimalRenderer, "run", fake_run)

    assert cmd_run_display(args) == 0
    assert seen["seconds"] == 0.0
    assert seen["fps"] == 12
    assert seen["scale"] == 1.5
    assert "drawables" in seen["render_snapshot"]


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
