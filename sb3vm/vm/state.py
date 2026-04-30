from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sb3vm.model.project import Project
from sb3vm.parse.ast_nodes import AskState, RuntimeDiagnostic, UnsupportedDiagnostic
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


@dataclass
class TargetState:
    instance_id: int
    source_target_name: str
    x: float = 0.0
    y: float = 0.0
    direction: float = 90.0
    rotation_style: str = "all around"
    visible: bool = True
    size: float = 100.0
    costume_index: int = 0
    layer_order: int = 0
    effects: dict[str, float] = field(default_factory=dict)
    dialogue: dict[str, Any] | None = None
    dialogue_token: int = 0
    local_variables: dict[str, Any] = field(default_factory=dict)
    local_lists: dict[str, list[Any]] = field(default_factory=dict)
    is_stage: bool = False
    is_clone: bool = False
    # Pen state
    pen_down: bool = False
    pen_color: tuple[int, int, int, int] = field(default_factory=lambda: (0, 0, 0, 255))
    pen_size: float = 1.0
    pen_shade: int = 50
    pen_hue: int = 120


@dataclass
class LoopState:
    kind: str
    body: list[Any]
    remaining: int | None = None
    condition: Any = None


@dataclass
class FrameState:
    kind: str
    stmts: list[Any]
    index: int = 0
    arguments: dict[str, Any] = field(default_factory=dict)
    proccode: str | None = None
    warp: bool = False
    loop: LoopState | None = None


@dataclass
class ThreadState:
    id: int
    instance_id: int
    frames: list[FrameState] = field(default_factory=list)
    root_target_name: str = ""
    root_trigger: str = ""
    spawn_order: int = 0
    wake_time: float = 0.0
    done: bool = False
    engine: str = "interpreted"
    script_key: str | None = None
    waiting_for_children: set[int] = field(default_factory=set)
    wait_reason: str | None = None
    waiting_for_answer: AskState | None = None
    dialogue_clear_instance_id: int | None = None
    dialogue_clear_token: int | None = None
    glide: dict[str, float] | None = None
    compiled_runner: Any = None
    current_stmt: Any = None

    def current_arguments(self) -> dict[str, Any]:
        for frame in reversed(self.frames):
            if frame.kind == "procedure":
                return frame.arguments
        return {}

    def in_warp(self) -> bool:
        return any(frame.kind == "procedure" and frame.warp for frame in self.frames)

    def call_depth(self) -> int:
        return sum(1 for frame in self.frames if frame.kind == "procedure")


@dataclass
class VMState:
    time_seconds: float = 0.0
    timer_started_at: float = 0.0
    stage_variables: dict[str, Any] = field(default_factory=dict)
    stage_lists: dict[str, list[Any]] = field(default_factory=dict)
    instances: dict[int, TargetState] = field(default_factory=dict)
    original_instance_ids: dict[str, int] = field(default_factory=dict)
    threads: dict[int, ThreadState] = field(default_factory=dict)
    unsupported_scripts: list[UnsupportedDiagnostic] = field(default_factory=list)
    runtime_diagnostics: list[RuntimeDiagnostic] = field(default_factory=list)
    music_tempo: float = 60.0

    @classmethod
    def from_project(cls, project: Project) -> "VMState":
        state = cls()
        next_instance_id = 1
        for target in project.targets:
            tstate = TargetState(
                instance_id=next_instance_id,
                source_target_name=target.name,
                x=target.x,
                y=target.y,
                direction=target.direction,
                rotation_style=target.rotation_style,
                visible=target.visible,
                size=target.size,
                costume_index=target.current_costume,
                layer_order=target.layer_order,
                effects={},
                local_variables={name: value for _, (name, value) in target.variables.items()},
                local_lists={name: list(value) for _, (name, value) in target.lists.items()},
                is_stage=target.is_stage,
                is_clone=False,
            )
            state.instances[next_instance_id] = tstate
            state.original_instance_ids[target.name] = next_instance_id
            if target.is_stage:
                state.stage_variables = tstate.local_variables
                state.stage_lists = tstate.local_lists
                try:
                    tempo = float(target.tempo)
                    if tempo > 0:
                        state.music_tempo = tempo
                except (TypeError, ValueError):
                    pass
            next_instance_id += 1
        return state

    def get_instance(self, instance_id: int) -> TargetState:
        return self.instances[instance_id]

    def get_original_instance_id(self, target_name: str) -> int:
        return self.original_instance_ids[target_name]

    def live_clone_count(self) -> int:
        return sum(1 for instance in self.instances.values() if instance.is_clone)

    @property
    def targets(self) -> dict[str, TargetState]:
        return {
            target_name: self.instances[instance_id]
            for target_name, instance_id in self.original_instance_ids.items()
            if instance_id in self.instances
        }

    def timer_seconds(self, override_seconds: float | None = None) -> float:
        if override_seconds is not None:
            return override_seconds
        return max(0.0, self.time_seconds - self.timer_started_at)

    def reset_timer(self) -> None:
        self.timer_started_at = self.time_seconds

    def snapshot(self, *, input_state: dict[str, object] | None = None, random_seed: int | None = None) -> dict[str, Any]:
        originals = {
            instance.source_target_name: self._instance_payload(instance)
            for instance in sorted(self.instances.values(), key=lambda item: item.instance_id)
            if not instance.is_clone
        }
        instances = {
            str(instance_id): self._instance_payload(instance)
            for instance_id, instance in sorted(self.instances.items())
        }
        thread_frames = {
            str(thread_id): {
                "instance_id": thread.instance_id,
                "source_target_name": self.instances[thread.instance_id].source_target_name if thread.instance_id in self.instances else None,
                "waiting_for_answer": thread.waiting_for_answer.prompt if thread.waiting_for_answer else None,
                "root_target_name": thread.root_target_name,
                "root_trigger": thread.root_trigger,
                "spawn_order": thread.spawn_order,
                "engine": thread.engine,
                "script_key": thread.script_key,
                "frames": [
                    {
                        "kind": frame.kind,
                        "index": frame.index,
                        "proccode": frame.proccode,
                        "warp": frame.warp,
                        "argument_names": sorted(frame.arguments),
                    }
                    for frame in thread.frames
                ],
            }
            for thread_id, thread in sorted(self.threads.items())
            if not thread.done
        }
        return {
            "time_seconds": self.time_seconds,
            "timer_seconds": self.timer_seconds((input_state or {}).get("timer_override") if input_state else None),
            "stage_variables": dict(sorted(self.stage_variables.items())),
            "stage_lists": {key: list(value) for key, value in sorted(self.stage_lists.items())},
            "targets": originals,
            "instances": instances,
            "clone_count": self.live_clone_count(),
            "active_threads": len([thread for thread in self.threads.values() if not thread.done]),
            "thread_frames": thread_frames,
            "unsupported_scripts": [item.to_dict() for item in self.unsupported_scripts],
            "runtime_diagnostics": [item.to_dict() for item in self.runtime_diagnostics],
            "input_state": {
                **(input_state or {}),
                "random_seed": random_seed,
            },
        }

    def render_snapshot(self, project: Project) -> dict[str, Any]:
        stage = self.targets["Stage"]
        ordered_instances = sorted(
            self.instances.values(),
            key=lambda item: (item.is_stage, item.layer_order, item.instance_id),
        )
        drawables = [
            {
                "draw_order": draw_order,
                "instance_id": instance.instance_id,
                "source_target_name": instance.source_target_name,
                "is_clone": instance.is_clone,
                "position": {
                    "x": instance.x,
                    "y": instance.y,
                },
                "direction": instance.direction,
                "rotation_style": instance.rotation_style,
                "visible": instance.visible,
                "size": instance.size,
                "layer_order": instance.layer_order,
                "effects": dict(sorted(instance.effects.items())),
                "dialogue": None if instance.dialogue is None else dict(instance.dialogue),
                "costume": self._costume_reference(project, instance.source_target_name, instance.costume_index),
                "collision": {
                    "api": "unavailable",
                    "reason": "renderer boundary only",
                },
            }
            for draw_order, instance in enumerate(item for item in ordered_instances if not item.is_stage)
        ]
        return {
            "coordinate_system": {
                "name": "scratch_stage",
                "origin": "center",
                "x_axis": "right",
                "y_axis": "up",
                "stage_width": 480,
                "stage_height": 360,
            },
            "layer_model": {
                "ordering": "back_to_front",
                "stage_is_base_layer": True,
            },
            "stage": {
                "instance_id": stage.instance_id,
                "source_target_name": stage.source_target_name,
                "backdrop": self._costume_reference(project, stage.source_target_name, stage.costume_index),
                "effects": dict(sorted(stage.effects.items())),
                "dialogue": None if stage.dialogue is None else dict(stage.dialogue),
            },
            "drawables": drawables,
            "collision_boundary": {
                "available": False,
                "coordinate_space": "scratch_stage",
                "requires_renderer": True,
            },
        }

    def _instance_payload(self, instance: TargetState) -> dict[str, Any]:
        return {
            "instance_id": instance.instance_id,
            "source_target_name": instance.source_target_name,
            "is_stage": instance.is_stage,
            "is_clone": instance.is_clone,
            "x": instance.x,
            "y": instance.y,
            "direction": instance.direction,
            "rotation_style": instance.rotation_style,
            "visible": instance.visible,
            "size": instance.size,
            "costume_index": instance.costume_index,
            "layer_order": instance.layer_order,
            "effects": dict(sorted(instance.effects.items())),
            "dialogue": None if instance.dialogue is None else dict(instance.dialogue),
            "variables": dict(sorted(instance.local_variables.items())),
            "lists": {key: list(value) for key, value in sorted(instance.local_lists.items())},
        }

    def _costume_reference(self, project: Project, target_name: str, costume_index: int) -> dict[str, Any]:
        target = project.get_target(target_name)
        costumes = target.costumes
        count = len(costumes)
        if not count:
            return {
                "target_name": target_name,
                "index": 0,
                "count": 0,
                "name": "",
                "asset_id": None,
                "md5ext": None,
            }
        resolved_index = costume_index % count
        costume = costumes[resolved_index]
        ref: dict[str, Any] = {
            "target_name": target_name,
            "index": resolved_index,
            "count": count,
            "name": costume.get("name", ""),
            "asset_id": costume.get("assetId"),
            "md5ext": costume.get("md5ext"),
        }
        rc_x = costume.get("rotationCenterX")
        rc_y = costume.get("rotationCenterY")
        if rc_x is not None:
            ref["rotationCenterX"] = rc_x
        if rc_y is not None:
            ref["rotationCenterY"] = rc_y
        return ref

