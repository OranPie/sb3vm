from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from sb3vm.model.project import Project
from sb3vm.vm.errors import Sb3VmError


class RendererError(Sb3VmError):
    pass


class RendererDependencyError(RendererError):
    pass


@dataclass
class RenderAssetStore:
    project: Project
    _image_cache: dict[str, Any] = field(default_factory=dict)

    def load_image(self, reference: dict[str, Any]) -> Any | None:
        md5ext = reference.get("md5ext")
        if not md5ext:
            return None
        if md5ext in self._image_cache:
            return self._image_cache[md5ext]
        payload = self.project.assets.get(md5ext)
        if payload is None:
            return None
        image = self._decode_image(md5ext, payload)
        self._image_cache[md5ext] = image
        return image

    def _decode_image(self, md5ext: str, payload: bytes) -> Any:
        try:
            from PIL import Image
        except ModuleNotFoundError as exc:
            raise RendererDependencyError(
                "Renderer requires Pillow. Install with `pip install 'sb3vm[render]'`."
            ) from exc

        lowered = md5ext.lower()
        if lowered.endswith(".svg"):
            payload = self._rasterize_svg(payload)
        image = Image.open(BytesIO(payload))
        return image.convert("RGBA")

    def _rasterize_svg(self, payload: bytes) -> bytes:
        try:
            import cairosvg
        except ModuleNotFoundError as exc:
            raise RendererDependencyError(
                "SVG rendering requires cairosvg. Install with `pip install 'sb3vm[render]'`."
            ) from exc
        return cairosvg.svg2png(bytestring=payload)
