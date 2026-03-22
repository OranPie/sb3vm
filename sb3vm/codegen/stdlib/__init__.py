from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def asset_id_from_filename(filename: str) -> str:
    return Path(filename).stem


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
    "SoundSpec",
    "asset_id_from_filename",
    "bitmap_costume",
    "mp3_sound",
    "svg_costume",
    "wav_sound",
]
