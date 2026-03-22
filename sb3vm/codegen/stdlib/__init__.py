from __future__ import annotations

import csv as _csv
import json as _json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from sb3vm.codegen.api import ScratchProject


def asset_id_from_filename(filename: str) -> str:
    return Path(filename).stem


@dataclass
class JsonNamespace:
    project: "ScratchProject"

    def dumps(self, value: Any, *, sort_keys: bool = False, ensure_ascii: bool = False) -> str:
        return _json.dumps(value, sort_keys=sort_keys, ensure_ascii=ensure_ascii)

    def loads(self, payload: str | bytes | bytearray) -> Any:
        return _json.loads(payload)


@dataclass
class CsvNamespace:
    project: "ScratchProject"

    def row(
        self,
        *values: Any,
        delimiter: str = ",",
        quotechar: str = '"',
        lineterminator: str = "",
    ) -> str:
        buffer: list[str] = []

        class _Buffer:
            def write(self, chunk: str) -> int:
                buffer.append(chunk)
                return len(chunk)

        writer = _csv.writer(_Buffer(), delimiter=delimiter, quotechar=quotechar, lineterminator=lineterminator)
        writer.writerow(["" if value is None else str(value) for value in values])
        return "".join(buffer)

    def rows(
        self,
        rows: list[list[Any]] | tuple[tuple[Any, ...], ...],
        *,
        delimiter: str = ",",
        quotechar: str = '"',
        lineterminator: str = "\n",
    ) -> str:
        return "".join(
            self.row(*row, delimiter=delimiter, quotechar=quotechar, lineterminator=lineterminator)
            for row in rows
        )

    def parse_row(self, payload: str, *, delimiter: str = ",", quotechar: str = '"') -> list[str]:
        return next(_csv.reader([payload], delimiter=delimiter, quotechar=quotechar), [])

    def parse_rows(self, payload: str, *, delimiter: str = ",", quotechar: str = '"') -> list[list[str]]:
        return [list(row) for row in _csv.reader(payload.splitlines(), delimiter=delimiter, quotechar=quotechar)]


@dataclass
class ExtensionNamespace:
    project: "ScratchProject"

    def enable(self, name: str) -> str:
        token = str(name).strip()
        if token and token not in self.project.extensions:
            self.project.extensions.append(token)
        return token

    def custom(self, name: str) -> str:
        return self.enable(name)

    def requests_network(self) -> str:
        return self.enable("requests")

    def pen(self) -> str:
        return self.enable("pen")

    def music(self) -> str:
        return self.enable("music")

    def text_to_speech(self) -> str:
        return self.enable("text2speech")

    def video_sensing(self) -> str:
        return self.enable("videoSensing")

    def translate(self) -> str:
        return self.enable("translate")


@dataclass
class ProjectStdlib:
    project: "ScratchProject"
    json: JsonNamespace = field(init=False)
    csv: CsvNamespace = field(init=False)
    extensions: ExtensionNamespace = field(init=False)

    def __post_init__(self) -> None:
        self.json = JsonNamespace(self.project)
        self.csv = CsvNamespace(self.project)
        self.extensions = ExtensionNamespace(self.project)


@dataclass(frozen=True)
class CostumeSpec:
    name: str
    asset_id: str
    data_format: str
    md5ext: str
    rotation_center_x: int | float
    rotation_center_y: int | float
    bitmap_resolution: int = 1
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "assetId": self.asset_id,
            "dataFormat": self.data_format,
            "md5ext": self.md5ext,
            "rotationCenterX": self.rotation_center_x,
            "rotationCenterY": self.rotation_center_y,
            "bitmapResolution": self.bitmap_resolution,
            **self.extras,
        }


@dataclass(frozen=True)
class SoundSpec:
    name: str
    asset_id: str
    data_format: str
    md5ext: str
    sample_count: int = 0
    rate: int = 0
    sound_format: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "assetId": self.asset_id,
            "dataFormat": self.data_format,
            "md5ext": self.md5ext,
            "sampleCount": self.sample_count,
            "rate": self.rate,
            **self.extras,
        }
        if self.sound_format:
            payload["format"] = self.sound_format
        return payload


def svg_costume(
    name: str,
    filename: str,
    *,
    asset_id: str | None = None,
    rotation_center_x: int | float = 0,
    rotation_center_y: int | float = 0,
    **extras: Any,
) -> CostumeSpec:
    return CostumeSpec(
        name=name,
        asset_id=asset_id or asset_id_from_filename(filename),
        data_format="svg",
        md5ext=filename,
        rotation_center_x=rotation_center_x,
        rotation_center_y=rotation_center_y,
        extras=dict(extras),
    )


def bitmap_costume(
    name: str,
    filename: str,
    *,
    asset_id: str | None = None,
    rotation_center_x: int | float = 0,
    rotation_center_y: int | float = 0,
    bitmap_resolution: int = 1,
    **extras: Any,
) -> CostumeSpec:
    suffix = Path(filename).suffix.lower().lstrip(".") or "png"
    return CostumeSpec(
        name=name,
        asset_id=asset_id or asset_id_from_filename(filename),
        data_format=suffix,
        md5ext=filename,
        rotation_center_x=rotation_center_x,
        rotation_center_y=rotation_center_y,
        bitmap_resolution=bitmap_resolution,
        extras=dict(extras),
    )


def wav_sound(
    name: str,
    filename: str,
    *,
    asset_id: str | None = None,
    sample_count: int = 0,
    rate: int = 0,
    sound_format: str = "",
    **extras: Any,
) -> SoundSpec:
    return SoundSpec(
        name=name,
        asset_id=asset_id or asset_id_from_filename(filename),
        data_format="wav",
        md5ext=filename,
        sample_count=sample_count,
        rate=rate,
        sound_format=sound_format,
        extras=dict(extras),
    )


def mp3_sound(
    name: str,
    filename: str,
    *,
    asset_id: str | None = None,
    sample_count: int = 0,
    rate: int = 0,
    **extras: Any,
) -> SoundSpec:
    return SoundSpec(
        name=name,
        asset_id=asset_id or asset_id_from_filename(filename),
        data_format="mp3",
        md5ext=filename,
        sample_count=sample_count,
        rate=rate,
        extras=dict(extras),
    )


__all__ = [
    "CostumeSpec",
    "CsvNamespace",
    "ExtensionNamespace",
    "JsonNamespace",
    "ProjectStdlib",
    "SoundSpec",
    "asset_id_from_filename",
    "bitmap_costume",
    "mp3_sound",
    "svg_costume",
    "wav_sound",
]
