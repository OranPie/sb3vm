from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class CgExpr:
    kind: str
    value: Any = None
    args: tuple["CgExpr", ...] = ()


@dataclass(frozen=True)
class CgStmt:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CgScript:
    target_name: str
    trigger_kind: str
    trigger_value: str | None
    body: tuple[CgStmt, ...]


@dataclass(frozen=True)
class CgProcedure:
    target_name: str
    name: str
    proccode: str
    argument_ids: tuple[str, ...]
    argument_names: tuple[str, ...]
    argument_defaults: tuple[Any, ...]
    warp: bool
    body: tuple[CgStmt, ...]


@dataclass(frozen=True)
class CgTarget:
    name: str
    is_stage: bool
    variables: tuple[tuple[str, Any], ...]
    lists: tuple[tuple[str, tuple[Any, ...]], ...]
    scripts: tuple[CgScript, ...]
    procedures: tuple[CgProcedure, ...]
    costumes: tuple[dict[str, Any], ...] = ()
    sounds: tuple[dict[str, Any], ...] = ()
    x: float = 0.0
    y: float = 0.0
    direction: float = 90.0
    size: float = 100.0
    visible: bool = True
    draggable: bool = False
    rotation_style: str = "all around"
    current_costume: int = 0
    volume: float = 100.0
    layer_order: int = 0
    tempo: float = 60.0
    video_transparency: float = 50.0
    video_state: str = "on"
    text_to_speech_language: str | None = None


@dataclass(frozen=True)
class CgProject:
    name: str
    targets: tuple[CgTarget, ...]
    broadcasts: tuple[str, ...]
    monitors: tuple[dict[str, Any], ...] = ()
    extensions: tuple[str, ...] = ()
    assets: tuple[tuple[str, bytes], ...] = ()
