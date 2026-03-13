from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sb3vm.vm.errors import ProjectValidationError


@dataclass
class Target:
    name: str
    is_stage: bool
    variables: dict[str, tuple[str, Any]]
    lists: dict[str, tuple[str, list[Any]]]
    broadcasts: dict[str, str]
    blocks: dict[str, dict[str, Any]]
    comments: dict[str, dict[str, Any]]
    costumes: list[dict[str, Any]]
    sounds: list[dict[str, Any]]
    current_costume: int = 0
    volume: float = 100.0
    layer_order: int = 0
    tempo: float = 60.0
    video_transparency: float = 50.0
    video_state: str = "on"
    text_to_speech_language: str | None = None
    x: float = 0.0
    y: float = 0.0
    direction: float = 90.0
    size: float = 100.0
    visible: bool = True
    draggable: bool = False
    rotation_style: str = "all around"
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Target":
        if not isinstance(data, dict):
            raise ProjectValidationError("Target entry must be an object")

        name = data.get("name", "")
        if not isinstance(name, str) or not name:
            raise ProjectValidationError("Target is missing a valid name")
        is_stage_raw = data.get("isStage", False)
        if not isinstance(is_stage_raw, bool):
            raise ProjectValidationError("Target field 'isStage' must be a boolean", target_name=name)

        return cls(
            name=name,
            is_stage=is_stage_raw,
            variables=_parse_variables(data.get("variables", {}), name),
            lists=_parse_lists(data.get("lists", {}), name),
            broadcasts=_parse_dict_of_scalars(data.get("broadcasts", {}), "broadcasts", name),
            blocks=_parse_blocks(data.get("blocks", {}), name),
            comments=_parse_nested_objects(data.get("comments", {}), "comments", name),
            costumes=_parse_object_list(data.get("costumes", []), "costumes", name),
            sounds=_parse_object_list(data.get("sounds", []), "sounds", name),
            current_costume=int(data.get("currentCostume", 0)),
            volume=float(data.get("volume", 100)),
            layer_order=int(data.get("layerOrder", 0)),
            tempo=float(data.get("tempo", 60)),
            video_transparency=float(data.get("videoTransparency", 50)),
            video_state=data.get("videoState", "on"),
            text_to_speech_language=data.get("textToSpeechLanguage"),
            x=float(data.get("x", 0)),
            y=float(data.get("y", 0)),
            direction=float(data.get("direction", 90)),
            size=float(data.get("size", 100)),
            visible=bool(data.get("visible", True)),
            draggable=bool(data.get("draggable", False)),
            rotation_style=data.get("rotationStyle", "all around"),
            raw=dict(data),
        )

    def to_json(self) -> dict[str, Any]:
        data = dict(self.raw)
        data.update(
            {
                "name": self.name,
                "isStage": self.is_stage,
                "variables": {k: [name, value] for k, (name, value) in self.variables.items()},
                "lists": {k: [name, value] for k, (name, value) in self.lists.items()},
                "broadcasts": dict(self.broadcasts),
                "blocks": self.blocks,
                "comments": self.comments,
                "costumes": self.costumes,
                "sounds": self.sounds,
                "currentCostume": self.current_costume,
                "volume": self.volume,
                "layerOrder": self.layer_order,
                "tempo": self.tempo,
                "videoTransparency": self.video_transparency,
                "videoState": self.video_state,
                "textToSpeechLanguage": self.text_to_speech_language,
                "x": self.x,
                "y": self.y,
                "direction": self.direction,
                "size": self.size,
                "visible": self.visible,
                "draggable": self.draggable,
                "rotationStyle": self.rotation_style,
            }
        )
        return data


@dataclass
class Project:
    targets: list[Target]
    monitors: list[dict[str, Any]]
    extensions: list[str]
    meta: dict[str, Any]
    assets: dict[str, bytes]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any], assets: dict[str, bytes] | None = None) -> "Project":
        if not isinstance(data, dict):
            raise ProjectValidationError("project.json must contain an object")
        targets_raw = data.get("targets", [])
        monitors_raw = data.get("monitors", [])
        extensions_raw = data.get("extensions", [])
        meta_raw = data.get("meta", {})
        if not isinstance(targets_raw, list):
            raise ProjectValidationError("Project field 'targets' must be a list")
        if not isinstance(monitors_raw, list):
            raise ProjectValidationError("Project field 'monitors' must be a list")
        if not isinstance(extensions_raw, list):
            raise ProjectValidationError("Project field 'extensions' must be a list")
        if not isinstance(meta_raw, dict):
            raise ProjectValidationError("Project field 'meta' must be an object")

        return cls(
            targets=[Target.from_json(t) for t in targets_raw],
            monitors=[dict(x) if isinstance(x, dict) else _raise_monitor_error() for x in monitors_raw],
            extensions=[str(x) for x in extensions_raw],
            meta=dict(meta_raw),
            assets=dict(assets or {}),
            raw=dict(data),
        )

    def to_json(self) -> dict[str, Any]:
        data = dict(self.raw)
        data.update(
            {
                "targets": [t.to_json() for t in self.targets],
                "monitors": self.monitors,
                "extensions": self.extensions,
                "meta": self.meta,
            }
        )
        return data

    def get_target(self, name: str) -> Target:
        for target in self.targets:
            if target.name == name:
                return target
        raise KeyError(name)


def _parse_variables(raw: Any, target_name: str) -> dict[str, tuple[str, Any]]:
    if not isinstance(raw, dict):
        raise ProjectValidationError("Target field 'variables' must be an object", target_name=target_name)
    parsed: dict[str, tuple[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, list) or len(value) < 2 or not isinstance(value[0], str):
            raise ProjectValidationError(
                "Variable entry must be [name, value]",
                target_name=target_name,
                reference=f"variables.{key}",
            )
        parsed[str(key)] = (value[0], value[1])
    return parsed


def _parse_lists(raw: Any, target_name: str) -> dict[str, tuple[str, list[Any]]]:
    if not isinstance(raw, dict):
        raise ProjectValidationError("Target field 'lists' must be an object", target_name=target_name)
    parsed: dict[str, tuple[str, list[Any]]] = {}
    for key, value in raw.items():
        if not isinstance(value, list) or len(value) < 2 or not isinstance(value[0], str) or not isinstance(value[1], list):
            raise ProjectValidationError(
                "List entry must be [name, values]",
                target_name=target_name,
                reference=f"lists.{key}",
            )
        parsed[str(key)] = (value[0], list(value[1]))
    return parsed


def _parse_blocks(raw: Any, target_name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ProjectValidationError("Target field 'blocks' must be an object", target_name=target_name)
    parsed: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise ProjectValidationError(
                "Block entry must be an object",
                target_name=target_name,
                block_id=str(key),
            )
        parsed[str(key)] = dict(value)
    return parsed


def _parse_nested_objects(raw: Any, field_name: str, target_name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ProjectValidationError(f"Target field '{field_name}' must be an object", target_name=target_name)
    parsed: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise ProjectValidationError(
                f"Target field '{field_name}' entries must be objects",
                target_name=target_name,
                reference=f"{field_name}.{key}",
            )
        parsed[str(key)] = dict(value)
    return parsed


def _parse_object_list(raw: Any, field_name: str, target_name: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ProjectValidationError(f"Target field '{field_name}' must be a list", target_name=target_name)
    parsed: list[dict[str, Any]] = []
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ProjectValidationError(
                f"Target field '{field_name}' entries must be objects",
                target_name=target_name,
                reference=f"{field_name}[{index}]",
            )
        parsed.append(dict(value))
    return parsed


def _parse_dict_of_scalars(raw: Any, field_name: str, target_name: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ProjectValidationError(f"Target field '{field_name}' must be an object", target_name=target_name)
    return {str(key): str(value) for key, value in raw.items()}


def _raise_monitor_error() -> dict[str, Any]:
    raise ProjectValidationError("Project field 'monitors' entries must be objects")
