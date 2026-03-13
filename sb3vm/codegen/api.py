from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


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
set_x = _authoring_only("set_x")
set_y = _authoring_only("set_y")
change_x_by = _authoring_only("change_x_by")
change_y_by = _authoring_only("change_y_by")
hide = _authoring_only("hide")
show = _authoring_only("show")
add_to_list = _authoring_only("add_to_list")
delete_from_list = _authoring_only("delete_from_list")
delete_all_of_list = _authoring_only("delete_all_of_list")
insert_at_list = _authoring_only("insert_at_list")
replace_in_list = _authoring_only("replace_in_list")
timer = _authoring_only("timer")
answer = _authoring_only("answer")
key_pressed = _authoring_only("key_pressed")
mouse_x = _authoring_only("mouse_x")
mouse_y = _authoring_only("mouse_y")
mouse_down = _authoring_only("mouse_down")
random_between = _authoring_only("random_between")


@dataclass(frozen=True)
class VariableHandle:
    target_name: str
    name: str
    default: Any = 0


@dataclass(frozen=True)
class ListHandle:
    target_name: str
    name: str
    initial: tuple[Any, ...] = ()


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


@dataclass
class TargetBuilder:
    project: "ScratchProject"
    name: str
    is_stage: bool
    x: float = 0.0
    y: float = 0.0
    visible: bool = True
    current_costume: int = 0
    variables: dict[str, VariableHandle] = field(default_factory=dict)
    lists: dict[str, ListHandle] = field(default_factory=dict)
    scripts: list[ScriptBinding] = field(default_factory=list)
    procedures: dict[str, ProcedureBinding] = field(default_factory=dict)
    costumes: list[dict[str, Any]] = field(default_factory=list)
    sounds: list[dict[str, Any]] = field(default_factory=list)

    def variable(self, name: str, default: Any = 0) -> VariableHandle:
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

    def procedure(self, *, warp: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.procedures[fn.__name__] = ProcedureBinding(target_name=self.name, function=fn, warp=warp)
            return fn

        return decorator


@dataclass
class ScratchProject:
    name: str = "Scratch Project"
    stage: TargetBuilder = field(init=False)
    sprites: list[TargetBuilder] = field(default_factory=list)
    broadcasts: set[str] = field(default_factory=set)

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

    def all_targets(self) -> list[TargetBuilder]:
        return [self.stage, *self.sprites]
