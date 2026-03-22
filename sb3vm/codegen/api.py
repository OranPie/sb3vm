from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)
SB3VM_INTERNAL_PREFIX = "__sb3vm_internal__"


class AuthoringRuntimeError(RuntimeError):
    pass


def _authoring_only(name: str) -> Callable[..., Any]:
    def inner(*args: Any, **kwargs: Any) -> Any:
        raise AuthoringRuntimeError(f"{name}() can only be used inside decorated Scratch authoring functions")

    inner.__name__ = name
    return inner


wait = _authoring_only("wait")
broadcast = _authoring_only("broadcast")
broadcast_wait = _authoring_only("broadcast_wait")
goto_xy = _authoring_only("goto_xy")
goto_target = _authoring_only("goto_target")
glide_xy = _authoring_only("glide_xy")
glide_to = _authoring_only("glide_to")
set_x = _authoring_only("set_x")
set_y = _authoring_only("set_y")
change_x_by = _authoring_only("change_x_by")
change_y_by = _authoring_only("change_y_by")
turn_right = _authoring_only("turn_right")
turn_left = _authoring_only("turn_left")
point_in_direction = _authoring_only("point_in_direction")
point_towards = _authoring_only("point_towards")
set_rotation_style = _authoring_only("set_rotation_style")
hide = _authoring_only("hide")
show = _authoring_only("show")
say = _authoring_only("say")
say_for_secs = _authoring_only("say_for_secs")
think = _authoring_only("think")
think_for_secs = _authoring_only("think_for_secs")
switch_costume = _authoring_only("switch_costume")
next_costume = _authoring_only("next_costume")
switch_backdrop = _authoring_only("switch_backdrop")
switch_backdrop_wait = _authoring_only("switch_backdrop_wait")
next_backdrop = _authoring_only("next_backdrop")
set_size = _authoring_only("set_size")
change_size_by = _authoring_only("change_size_by")
set_effect = _authoring_only("set_effect")
change_effect_by = _authoring_only("change_effect_by")
clear_graphic_effects = _authoring_only("clear_graphic_effects")
go_front_back = _authoring_only("go_front_back")
go_layers = _authoring_only("go_layers")
add_to_list = _authoring_only("add_to_list")
delete_from_list = _authoring_only("delete_from_list")
delete_all_of_list = _authoring_only("delete_all_of_list")
insert_at_list = _authoring_only("insert_at_list")
replace_in_list = _authoring_only("replace_in_list")
create_clone = _authoring_only("create_clone")
delete_this_clone = _authoring_only("delete_this_clone")
ask = _authoring_only("ask")
reset_timer = _authoring_only("reset_timer")
play_note_for_beats = _authoring_only("play_note_for_beats")
stop = _authoring_only("stop")
timer = _authoring_only("timer")
answer = _authoring_only("answer")
key_pressed = _authoring_only("key_pressed")
mouse_x = _authoring_only("mouse_x")
mouse_y = _authoring_only("mouse_y")
mouse_down = _authoring_only("mouse_down")
touching_object = _authoring_only("touching_object")
x_position = _authoring_only("x_position")
y_position = _authoring_only("y_position")
direction = _authoring_only("direction")
size = _authoring_only("size")
costume_number = _authoring_only("costume_number")
costume_name = _authoring_only("costume_name")
backdrop_number = _authoring_only("backdrop_number")
backdrop_name = _authoring_only("backdrop_name")
list_item = _authoring_only("list_item")
list_length = _authoring_only("list_length")
list_contains = _authoring_only("list_contains")
list_contents = _authoring_only("list_contents")
join = _authoring_only("join")
letter_of = _authoring_only("letter_of")
string_length = _authoring_only("string_length")
string_contains = _authoring_only("string_contains")
round_value = _authoring_only("round_value")
math_op = _authoring_only("math_op")
random_between = _authoring_only("random_between")


@dataclass(frozen=True)
class VariableHandle:
    target_name: str
    name: str
    default: Any = 0

    def get(self) -> Any:
        return _authoring_only("VariableHandle.get")(self)

    def value(self) -> Any:
        return _authoring_only("VariableHandle.value")(self)

    def set(self, value: Any) -> Any:
        return _authoring_only("VariableHandle.set")(self, value)

    def change(self, value: Any) -> Any:
        return _authoring_only("VariableHandle.change")(self, value)

    def join(self, other: Any) -> Any:
        return _authoring_only("VariableHandle.join")(self, other)

    def letter(self, index: Any) -> Any:
        return _authoring_only("VariableHandle.letter")(self, index)

    def length(self) -> Any:
        return _authoring_only("VariableHandle.length")(self)

    def contains(self, part: Any) -> Any:
        return _authoring_only("VariableHandle.contains")(self, part)

    def rounded(self) -> Any:
        return _authoring_only("VariableHandle.rounded")(self)

    def math(self, op: str) -> Any:
        return _authoring_only("VariableHandle.math")(self, op)


@dataclass(frozen=True)
class ListHandle:
    target_name: str
    name: str
    initial: tuple[Any, ...] = ()

    def append(self, item: Any) -> Any:
        return _authoring_only("ListHandle.append")(self, item)

    def push(self, item: Any) -> Any:
        return _authoring_only("ListHandle.push")(self, item)

    def delete(self, index: Any) -> Any:
        return _authoring_only("ListHandle.delete")(self, index)

    def remove(self, index: Any) -> Any:
        return _authoring_only("ListHandle.remove")(self, index)

    def clear(self) -> Any:
        return _authoring_only("ListHandle.clear")()

    def insert(self, index: Any, item: Any) -> Any:
        return _authoring_only("ListHandle.insert")(self, index, item)

    def replace(self, index: Any, item: Any) -> Any:
        return _authoring_only("ListHandle.replace")(self, index, item)

    def item(self, index: Any) -> Any:
        return _authoring_only("ListHandle.item")(self, index)

    def at(self, index: Any) -> Any:
        return _authoring_only("ListHandle.at")(self, index)

    def length(self) -> Any:
        return _authoring_only("ListHandle.length")(self)

    def contains(self, item: Any) -> Any:
        return _authoring_only("ListHandle.contains")(self, item)

    def has(self, item: Any) -> Any:
        return _authoring_only("ListHandle.has")(self, item)

    def contents(self) -> Any:
        return _authoring_only("ListHandle.contents")(self)

    def text(self) -> Any:
        return _authoring_only("ListHandle.text")(self)


@dataclass(frozen=True)
class ScratchConstant:
    value: str


class ScratchEnum(str, Enum):
    pass


class GraphicEffect(ScratchEnum):
    COLOR = "color"
    FISHEYE = "fisheye"
    WHIRL = "whirl"
    PIXELATE = "pixelate"
    MOSAIC = "mosaic"
    BRIGHTNESS = "brightness"
    GHOST = "ghost"


class RotationStyle(ScratchEnum):
    ALL_AROUND = "all around"
    LEFT_RIGHT = "left-right"
    DONT_ROTATE = "don't rotate"


class LayerPosition(ScratchEnum):
    FRONT = "front"
    BACK = "back"


class LayerDirection(ScratchEnum):
    FORWARD = "forward"
    BACKWARD = "backward"


class StopTarget(ScratchEnum):
    ALL = "all"
    THIS_SCRIPT = "this script"
    OTHER_SCRIPTS_IN_SPRITE = "other scripts in sprite"


MYSELF = ScratchConstant("_myself_")
MOUSE_POINTER = ScratchConstant("_mouse_")
EDGE = ScratchConstant("_edge_")
RANDOM_POSITION = ScratchConstant("_random_")


@dataclass
class ScriptBinding:
    kind: str
    target_name: str
    trigger_value: str | None
    function: Callable[..., Any]


@dataclass
class ProcedureBinding:
    target_name: str
    function: Callable[..., Any]
    warp: bool = False
    proccode: str | None = None
    argument_names: tuple[str, ...] | None = None
    argument_defaults: tuple[Any, ...] | None = None
    returns_value: bool = False
    return_variable: str | None = None


@dataclass
class TargetBuilder:
    project: "ScratchProject"
    name: str
    is_stage: bool
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
    variables: dict[str, VariableHandle] = field(default_factory=dict)
    lists: dict[str, ListHandle] = field(default_factory=dict)
    scripts: list[ScriptBinding] = field(default_factory=list)
    procedures: dict[str, ProcedureBinding] = field(default_factory=dict)
    costumes: list[dict[str, Any]] = field(default_factory=list)
    sounds: list[dict[str, Any]] = field(default_factory=list)
    _internal_variable_counter: int = 0

    def variable(self, name: str, default: Any = 0) -> VariableHandle:
        handle = VariableHandle(self.name, name, default)
        self.variables[name] = handle
        return handle

    def internal_variable(self, category: str, *, default: Any = "", hint: str | None = None) -> VariableHandle:
        token = re.sub(r"\W+", "_", hint or category).strip("_").lower() or category
        base = f"{SB3VM_INTERNAL_PREFIX}{category}__{token}"
        name = base
        while name in self.variables:
            self._internal_variable_counter += 1
            name = f"{base}_{self._internal_variable_counter}"
        handle = VariableHandle(self.name, name, default)
        self.variables[name] = handle
        return handle

    def list(self, name: str, initial: list[Any] | None = None) -> ListHandle:
        handle = ListHandle(self.name, name, tuple(initial or []))
        self.lists[name] = handle
        return handle

    def when_flag_clicked(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.scripts.append(ScriptBinding(kind="green_flag", target_name=self.name, trigger_value=None, function=fn))
            return fn

        return decorator

    def when_broadcast_received(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        self.project.register_broadcast(name)

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.scripts.append(ScriptBinding(kind="broadcast_received", target_name=self.name, trigger_value=name, function=fn))
            return fn

        return decorator

    def when_key_pressed(self, key: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.scripts.append(ScriptBinding(kind="key_pressed", target_name=self.name, trigger_value=key, function=fn))
            return fn

        return decorator

    def when_backdrop_switched_to(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.scripts.append(ScriptBinding(kind="backdrop_switched", target_name=self.name, trigger_value=name, function=fn))
            return fn

        return decorator

    def when_started_as_clone(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.scripts.append(ScriptBinding(kind="clone_start", target_name=self.name, trigger_value=None, function=fn))
            return fn

        return decorator

    def procedure(
        self,
        *,
        warp: bool = False,
        proccode: str | None = None,
        argument_names: tuple[str, ...] | None = None,
        argument_defaults: tuple[Any, ...] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.procedures[fn.__name__] = ProcedureBinding(
                target_name=self.name,
                function=fn,
                warp=warp,
                proccode=proccode,
                argument_names=argument_names,
                argument_defaults=argument_defaults,
            )
            return fn

        return decorator

    def add_costume(self, costume: Any) -> None:
        self.costumes.append(_coerce_project_record(costume))

    def wait(self, duration: Any) -> Any:
        return wait(duration)

    def broadcast(self, name: str) -> Any:
        return broadcast(name)

    def broadcast_wait(self, name: str) -> Any:
        return broadcast_wait(name)

    def goto_xy(self, x: Any, y: Any) -> Any:
        return goto_xy(x, y)

    def goto_target(self, target: Any) -> Any:
        return goto_target(target)

    def glide_xy(self, duration: Any, x: Any, y: Any) -> Any:
        return glide_xy(duration, x, y)

    def glide_to(self, duration: Any, target: Any) -> Any:
        return glide_to(duration, target)

    def set_x(self, x: Any) -> Any:
        return set_x(x)

    def set_y(self, y: Any) -> Any:
        return set_y(y)

    def change_x_by(self, dx: Any) -> Any:
        return change_x_by(dx)

    def change_y_by(self, dy: Any) -> Any:
        return change_y_by(dy)

    def turn_right(self, degrees: Any) -> Any:
        return turn_right(degrees)

    def turn_left(self, degrees: Any) -> Any:
        return turn_left(degrees)

    def point_in_direction(self, direction_value: Any) -> Any:
        return point_in_direction(direction_value)

    def point_towards(self, target: Any) -> Any:
        return point_towards(target)

    def set_rotation_style(self, style: Any) -> Any:
        return set_rotation_style(style)

    def hide(self) -> Any:
        return hide()

    def show(self) -> Any:
        return show()

    def say(self, message: Any) -> Any:
        return say(message)

    def say_for_secs(self, message: Any, duration: Any) -> Any:
        return say_for_secs(message, duration)

    def think(self, message: Any) -> Any:
        return think(message)

    def think_for_secs(self, message: Any, duration: Any) -> Any:
        return think_for_secs(message, duration)

    def switch_costume(self, costume: Any) -> Any:
        return switch_costume(costume)

    def next_costume(self) -> Any:
        return next_costume()

    def switch_backdrop(self, backdrop: Any) -> Any:
        return switch_backdrop(backdrop)

    def switch_backdrop_wait(self, backdrop: Any) -> Any:
        return switch_backdrop_wait(backdrop)

    def next_backdrop(self) -> Any:
        return next_backdrop()

    def set_size(self, size_value: Any) -> Any:
        return set_size(size_value)

    def change_size_by(self, delta: Any) -> Any:
        return change_size_by(delta)

    def set_effect(self, effect: Any, value: Any) -> Any:
        return set_effect(effect, value)

    def change_effect_by(self, effect: Any, value: Any) -> Any:
        return change_effect_by(effect, value)

    def clear_graphic_effects(self) -> Any:
        return clear_graphic_effects()

    def go_front_back(self, direction_value: Any) -> Any:
        return go_front_back(direction_value)

    def go_layers(self, direction_value: Any, layers: Any) -> Any:
        return go_layers(direction_value, layers)

    def create_clone(self, selector: Any) -> Any:
        return create_clone(selector)

    def delete_this_clone(self) -> Any:
        return delete_this_clone()

    def ask(self, prompt: Any) -> Any:
        return ask(prompt)

    def reset_timer(self) -> Any:
        return reset_timer()

    def play_note_for_beats(self, note: Any, beats: Any) -> Any:
        return play_note_for_beats(note, beats)

    def stop(self, mode: Any) -> Any:
        return stop(mode)

    def touching_object(self, target: Any) -> Any:
        return touching_object(target)

    def x_position(self) -> Any:
        return x_position()

    def y_position(self) -> Any:
        return y_position()

    def direction_value(self) -> Any:
        return direction()

    def size_value(self) -> Any:
        return size()

    def costume_name(self) -> Any:
        return costume_name()

    def costume_number(self) -> Any:
        return costume_number()

    def backdrop_name(self) -> Any:
        return backdrop_name()

    def backdrop_number(self) -> Any:
        return backdrop_number()

    def add_sound(self, sound: Any) -> None:
        self.sounds.append(_coerce_project_record(sound))


@dataclass
class ScratchProject:
    name: str = "Scratch Project"
    stage: TargetBuilder = field(init=False)
    sprites: list[TargetBuilder] = field(default_factory=list)
    broadcasts: set[str] = field(default_factory=set)
    extensions: list[str] = field(default_factory=list)
    assets: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stage = TargetBuilder(project=self, name="Stage", is_stage=True)

    def sprite(
        self,
        name: str,
        *,
        x: float = 0.0,
        y: float = 0.0,
        visible: bool = True,
        current_costume: int = 0,
    ) -> TargetBuilder:
        target = TargetBuilder(
            project=self,
            name=name,
            is_stage=False,
            x=x,
            y=y,
            visible=visible,
            current_costume=current_costume,
        )
        self.sprites.append(target)
        return target

    def register_broadcast(self, name: str) -> None:
        if name:
            self.broadcasts.add(name)

    def add_asset(self, name: str, payload: bytes) -> None:
        self.assets[name] = payload

    def all_targets(self) -> list[TargetBuilder]:
        return [self.stage, *self.sprites]


def _coerce_project_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if not isinstance(data, dict):
            raise TypeError("Authoring record to_dict() must return a dict")
        return dict(data)
    raise TypeError("Authoring records must be dict-like or provide to_dict()")
