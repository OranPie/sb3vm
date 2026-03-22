from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from sb3vm.codegen.api import ListHandle, ProcedureBinding, ScratchConstant, ScratchEnum, ScratchProject, TargetBuilder, VariableHandle
from sb3vm.codegen.ir import CgExpr, CgProcedure, CgProject, CgScript, CgStmt, CgTarget
from sb3vm.io.save_sb3 import save_sb3
from sb3vm.log import debug, error, get_logger, info
from sb3vm.model.project import Project
from sb3vm.vm.errors import Sb3VmError
from sb3vm.vm.runtime import Sb3Vm


_LOGGER = get_logger(__name__)


class CodegenError(Sb3VmError):
    pass


_MISSING = object()


def _resolve_static_object(node: ast.AST, context: CompileContext) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in context.parameters:
            return _MISSING
        return context.module_globals.get(node.id, _MISSING)
    if isinstance(node, ast.Attribute):
        base = _resolve_static_object(node.value, context)
        if base is _MISSING:
            return _MISSING
        return getattr(base, node.attr, _MISSING)
    return _MISSING


def load_authoring_module(path: str | Path) -> ModuleType:
    source_path = Path(path)
    info(_LOGGER, "codegen.load_authoring_module", "loading authoring module %s", source_path)
    module_name = f"sb3vm_codegen_{source_path.stem}_{abs(hash(source_path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        error(_LOGGER, "codegen.load_authoring_module", "unable to create import spec for %s", source_path)
        raise CodegenError(f"Unable to load authoring module: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    debug(_LOGGER, "codegen.load_authoring_module", "loaded module %s from %s", module_name, source_path)
    return module


def get_authoring_project(module: ModuleType, attr: str = "project") -> ScratchProject:
    candidate = getattr(module, attr, None)
    if not isinstance(candidate, ScratchProject):
        raise CodegenError(f"Authoring module is missing ScratchProject attribute {attr!r}")
    return candidate


def build_project(source: str | Path | ModuleType, *, project_attr: str = "project") -> Project:
    info(_LOGGER, "codegen.build_project", "building project from %s attr=%s", source, project_attr)
    module = load_authoring_module(source) if not isinstance(source, ModuleType) else source
    authoring = get_authoring_project(module, project_attr)
    ir_project = lower_authoring_project(authoring)
    project = emit_project(ir_project)
    info(
        _LOGGER,
        "codegen.build_project",
        "built project targets=%d broadcasts=%d",
        len(project.targets),
        sum(len(target.broadcasts) for target in project.targets),
    )
    return project


def run_authored_project(
    source: str | Path | ModuleType,
    *,
    project_attr: str = "project",
    seconds: float = 1.0,
    dt: float = 1 / 30,
) -> tuple[Project, Sb3Vm]:
    info(_LOGGER, "codegen.run_authored_project", "running authored project source=%s seconds=%.3f dt=%.5f", source, seconds, dt)
    project = build_project(source, project_attr=project_attr)
    vm = Sb3Vm(project)
    vm.run_for(seconds, dt=dt)
    info(_LOGGER, "codegen.run_authored_project", "run completed time=%.3f threads=%d", vm.state.time_seconds, len(vm.state.threads))
    return project, vm


@dataclass
class CompileContext:
    module_globals: dict[str, Any]
    target: TargetBuilder
    procedures: dict[str, ProcedureBinding]
    project: ScratchProject
    parameters: tuple[str, ...] = ()
    parameter_display_names: dict[str, str] = field(default_factory=dict)


def lower_authoring_project(authoring: ScratchProject) -> CgProject:
    debug(_LOGGER, "codegen.lower_authoring_project", "lowering project name=%s targets=%d", authoring.name, len(authoring.all_targets()))
    broadcasts = set(authoring.broadcasts)
    targets: list[CgTarget] = []
    for target in authoring.all_targets():
        scripts: list[CgScript] = []
        procedures: list[CgProcedure] = []
        proc_bindings = dict(target.procedures)
        for binding in target.scripts:
            body = lower_function(binding.function, target, authoring, parameters=(), procedures=proc_bindings)
            scripts.append(
                CgScript(
                    target_name=target.name,
                    trigger_kind=binding.kind,
                    trigger_value=binding.trigger_value,
                    body=tuple(body),
                )
            )
            if binding.kind == "broadcast_received" and binding.trigger_value:
                broadcasts.add(binding.trigger_value)
        for name, binding in proc_bindings.items():
            fn_node = get_function_ast(binding.function)
            python_argument_names = tuple(arg.arg for arg in fn_node.args.args)
            argument_names = _binding_argument_names(binding, python_argument_names)
            argument_defaults = _binding_argument_defaults(binding, len(python_argument_names))
            body = lower_function(
                binding.function,
                target,
                authoring,
                parameters=python_argument_names,
                procedures=proc_bindings,
                parameter_display_names=dict(zip(python_argument_names, argument_names)),
            )
            procedures.append(
                CgProcedure(
                    target_name=target.name,
                    name=name,
                    proccode=binding.proccode or _procedure_proccode(name, argument_names),
                    argument_ids=tuple(f"arg:{name}:{index}" for index, _ in enumerate(argument_names)),
                    argument_names=argument_names,
                    argument_defaults=argument_defaults,
                    warp=binding.warp,
                    body=tuple(body),
                )
            )
        targets.append(
            CgTarget(
                name=target.name,
                is_stage=target.is_stage,
                variables=tuple((name, handle.default) for name, handle in target.variables.items()),
                lists=tuple((name, handle.initial) for name, handle in target.lists.items()),
                scripts=tuple(scripts),
                procedures=tuple(procedures),
                costumes=tuple(target.costumes),
                sounds=tuple(target.sounds),
                x=target.x,
                y=target.y,
                direction=target.direction,
                size=target.size,
                visible=target.visible,
                draggable=target.draggable,
                rotation_style=target.rotation_style,
                current_costume=target.current_costume,
                volume=target.volume,
                layer_order=target.layer_order,
                tempo=target.tempo,
                video_transparency=target.video_transparency,
                video_state=target.video_state,
                text_to_speech_language=target.text_to_speech_language,
            )
        )
    project = CgProject(
        name=authoring.name,
        targets=tuple(targets),
        broadcasts=tuple(sorted(broadcasts)),
        extensions=tuple(authoring.extensions),
        assets=tuple(sorted(authoring.assets.items())),
    )
    debug(_LOGGER, "codegen.lower_authoring_project", "lowered target_count=%d procedure_count=%d", len(project.targets), sum(len(target.procedures) for target in project.targets))
    return project


def get_function_ast(fn: Any) -> ast.FunctionDef:
    source = textwrap.dedent(inspect.getsource(fn))
    module_ast = ast.parse(source)
    node = module_ast.body[0]
    if not isinstance(node, ast.FunctionDef):
        raise CodegenError(f"Unsupported authoring object {fn!r}")
    return node


def lower_function(
    fn: Any,
    target: TargetBuilder,
    project: ScratchProject,
    *,
    parameters: tuple[str, ...],
    procedures: dict[str, ProcedureBinding],
    parameter_display_names: dict[str, str] | None = None,
) -> list[CgStmt]:
    fn_node = get_function_ast(fn)
    context = CompileContext(
        module_globals=fn.__globals__,
        target=target,
        project=project,
        procedures=procedures,
        parameters=parameters,
        parameter_display_names=dict(parameter_display_names or {}),
    )
    return [stmt for node in fn_node.body for stmt in lower_stmt(node, context)]


def _resolve_method_receiver(node: ast.AST, context: CompileContext) -> tuple[Any, str] | None:
    if not isinstance(node, ast.Attribute):
        return None
    receiver = _resolve_static_object(node.value, context)
    if receiver is _MISSING:
        return None
    return receiver, node.attr


def _require_current_target_receiver(receiver: Any, context: CompileContext) -> None:
    if not isinstance(receiver, TargetBuilder) or receiver.name != context.target.name:
        raise CodegenError("Target method sugar can only be used on the current target in v1")


def lower_stmt(node: ast.stmt, context: CompileContext) -> list[CgStmt]:
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise CodegenError("Only simple assignment to declared Scratch variables is supported")
        target_name = node.targets[0].id
        handle = _resolve_variable(target_name, context)
        return [CgStmt("set_var", {"name": handle.name, "value": lower_expr(node.value, context)})]
    if isinstance(node, ast.AugAssign):
        if not isinstance(node.target, ast.Name):
            raise CodegenError("Only simple augmented assignment to declared Scratch variables is supported")
        handle = _resolve_variable(node.target.id, context)
        if not isinstance(node.op, ast.Add):
            raise CodegenError("Only += is supported for Scratch variable augmented assignment")
        return [CgStmt("change_var", {"name": handle.name, "value": lower_expr(node.value, context)})]
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return [lower_call_stmt(node.value, context)]
    if isinstance(node, ast.If):
        kind = "if_else" if node.orelse else "if"
        stmt = CgStmt(
            kind,
            {
                "condition": lower_expr(node.test, context),
                "body": tuple(stmt for item in node.body for stmt in lower_stmt(item, context)),
                "else_body": tuple(stmt for item in node.orelse for stmt in lower_stmt(item, context)),
            },
        )
        return [stmt]
    if isinstance(node, ast.For):
        if not (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
            and len(node.iter.args) == 1
        ):
            raise CodegenError("Only for ... in range(expr) loops are supported")
        return [
            CgStmt(
                "repeat",
                {
                    "times": lower_expr(node.iter.args[0], context),
                    "body": tuple(stmt for item in node.body for stmt in lower_stmt(item, context)),
                },
            )
        ]
    if isinstance(node, ast.While):
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            return [CgStmt("forever", {"body": tuple(stmt for item in node.body for stmt in lower_stmt(item, context))})]
        return [
            CgStmt(
                "repeat_until",
                {
                    "condition": lower_expr(ast.UnaryOp(op=ast.Not(), operand=node.test), context),
                    "body": tuple(stmt for item in node.body for stmt in lower_stmt(item, context)),
                },
            )
        ]
    if isinstance(node, ast.Return):
        if node.value is not None:
            raise CodegenError("Scratch procedures do not support return values")
        return []
    if isinstance(node, ast.Pass):
        return []
    raise CodegenError(f"Unsupported statement syntax: {node.__class__.__name__}")


def lower_call_stmt(node: ast.Call, context: CompileContext) -> CgStmt:
    method = _resolve_method_receiver(node.func, context)
    if method is not None:
        receiver, name = method
        if isinstance(receiver, VariableHandle):
            if name == "set" and len(node.args) == 1:
                return CgStmt("set_var", {"name": receiver.name, "value": lower_expr(node.args[0], context)})
            if name == "change" and len(node.args) == 1:
                return CgStmt("change_var", {"name": receiver.name, "value": lower_expr(node.args[0], context)})
        if isinstance(receiver, ListHandle):
            if name == "append" and len(node.args) == 1:
                return CgStmt("list_add", {"name": receiver.name, "item": lower_expr(node.args[0], context)})
            if name == "delete" and len(node.args) == 1:
                return CgStmt("list_delete", {"name": receiver.name, "index": lower_expr(node.args[0], context)})
            if name == "clear" and not node.args:
                return CgStmt("list_delete_all", {"name": receiver.name})
            if name == "insert" and len(node.args) == 2:
                return CgStmt("list_insert", {"name": receiver.name, "index": lower_expr(node.args[0], context), "item": lower_expr(node.args[1], context)})
            if name == "replace" and len(node.args) == 2:
                return CgStmt("list_replace", {"name": receiver.name, "index": lower_expr(node.args[0], context), "item": lower_expr(node.args[1], context)})
        if isinstance(receiver, TargetBuilder):
            _require_current_target_receiver(receiver, context)
            if name == "wait" and len(node.args) == 1:
                return CgStmt("wait", {"duration": lower_expr(node.args[0], context)})
            if name == "broadcast" and len(node.args) == 1:
                literal = _require_string_literal(node.args[0], context)
                context.project.register_broadcast(literal)
                return CgStmt("broadcast", {"name": literal, "wait": False})
            if name == "broadcast_wait" and len(node.args) == 1:
                literal = _require_string_literal(node.args[0], context)
                context.project.register_broadcast(literal)
                return CgStmt("broadcast", {"name": literal, "wait": True})
            if name == "goto_xy" and len(node.args) == 2:
                return CgStmt("move_state", {"mode": "goto_xy", "x": lower_expr(node.args[0], context), "y": lower_expr(node.args[1], context)})
            if name == "goto_target" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "goto_target", "target": lower_expr(node.args[0], context)})
            if name == "glide_xy" and len(node.args) == 3:
                return CgStmt("move_state", {"mode": "glide_xy", "duration": lower_expr(node.args[0], context), "x": lower_expr(node.args[1], context), "y": lower_expr(node.args[2], context)})
            if name == "glide_to" and len(node.args) == 2:
                return CgStmt("move_state", {"mode": "glide_target", "duration": lower_expr(node.args[0], context), "target": lower_expr(node.args[1], context)})
            if name == "set_x" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "set_x", "x": lower_expr(node.args[0], context)})
            if name == "set_y" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "set_y", "y": lower_expr(node.args[0], context)})
            if name == "change_x_by" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "change_x", "dx": lower_expr(node.args[0], context)})
            if name == "change_y_by" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "change_y", "dy": lower_expr(node.args[0], context)})
            if name == "turn_right" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "turn_right", "degrees": lower_expr(node.args[0], context)})
            if name == "turn_left" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "turn_left", "degrees": lower_expr(node.args[0], context)})
            if name == "point_in_direction" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "point_direction", "direction": lower_expr(node.args[0], context)})
            if name == "point_towards" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "point_towards", "target": lower_expr(node.args[0], context)})
            if name == "set_rotation_style" and len(node.args) == 1:
                return CgStmt("move_state", {"mode": "set_rotation_style", "style": _require_string_literal(node.args[0], context)})
            if name == "hide" and not node.args:
                return CgStmt("looks_state", {"mode": "hide"})
            if name == "show" and not node.args:
                return CgStmt("looks_state", {"mode": "show"})
            if name == "say" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "dialogue", "style": "say", "message": lower_expr(node.args[0], context)})
            if name == "say_for_secs" and len(node.args) == 2:
                return CgStmt("looks_state", {"mode": "dialogue", "style": "say", "message": lower_expr(node.args[0], context), "duration": lower_expr(node.args[1], context)})
            if name == "think" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "dialogue", "style": "think", "message": lower_expr(node.args[0], context)})
            if name == "think_for_secs" and len(node.args) == 2:
                return CgStmt("looks_state", {"mode": "dialogue", "style": "think", "message": lower_expr(node.args[0], context), "duration": lower_expr(node.args[1], context)})
            if name == "switch_costume" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "switch_costume", "costume": lower_expr(node.args[0], context)})
            if name == "next_costume" and not node.args:
                return CgStmt("looks_state", {"mode": "next_costume"})
            if name == "switch_backdrop" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "switch_backdrop", "backdrop": lower_expr(node.args[0], context), "wait": False})
            if name == "switch_backdrop_wait" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "switch_backdrop", "backdrop": lower_expr(node.args[0], context), "wait": True})
            if name == "next_backdrop" and not node.args:
                return CgStmt("looks_state", {"mode": "next_backdrop"})
            if name == "set_size" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "set_size", "size": lower_expr(node.args[0], context)})
            if name == "change_size_by" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "change_size", "delta": lower_expr(node.args[0], context)})
            if name == "set_effect" and len(node.args) == 2:
                return CgStmt("looks_state", {"mode": "set_effect", "effect": _require_string_literal(node.args[0], context), "value": lower_expr(node.args[1], context)})
            if name == "change_effect_by" and len(node.args) == 2:
                return CgStmt("looks_state", {"mode": "change_effect", "effect": _require_string_literal(node.args[0], context), "value": lower_expr(node.args[1], context)})
            if name == "clear_graphic_effects" and not node.args:
                return CgStmt("looks_state", {"mode": "clear_effects"})
            if name == "go_front_back" and len(node.args) == 1:
                return CgStmt("looks_state", {"mode": "go_front_back", "direction": _require_string_literal(node.args[0], context)})
            if name == "go_layers" and len(node.args) == 2:
                return CgStmt("looks_state", {"mode": "go_layers", "direction": _require_string_literal(node.args[0], context), "layers": lower_expr(node.args[1], context)})
            if name == "create_clone" and len(node.args) == 1:
                return CgStmt("create_clone", {"selector": lower_expr(node.args[0], context)})
            if name == "delete_this_clone" and not node.args:
                return CgStmt("delete_clone", {})
            if name == "ask" and len(node.args) == 1:
                return CgStmt("ask", {"prompt": lower_expr(node.args[0], context)})
            if name == "reset_timer" and not node.args:
                return CgStmt("reset_timer", {})
            if name == "play_note_for_beats" and len(node.args) == 2:
                return CgStmt("music_play_note", {"note": lower_expr(node.args[0], context), "beats": lower_expr(node.args[1], context)})
            if name == "stop" and len(node.args) == 1:
                return CgStmt("stop", {"mode": _require_string_literal(node.args[0], context)})
        raise CodegenError(f"Unsupported method call in authoring bodies: {ast.unparse(node.func)}")
    if not isinstance(node.func, ast.Name):
        raise CodegenError("Only direct function calls are supported in authoring bodies")
    name = node.func.id
    if name == "add_to_list" and len(node.args) == 2:
        handle = _require_list_handle(node.args[0], context)
        return CgStmt("list_add", {"name": handle.name, "item": lower_expr(node.args[1], context)})
    if name == "delete_from_list" and len(node.args) == 2:
        handle = _require_list_handle(node.args[0], context)
        return CgStmt("list_delete", {"name": handle.name, "index": lower_expr(node.args[1], context)})
    if name == "delete_all_of_list" and len(node.args) == 1:
        handle = _require_list_handle(node.args[0], context)
        return CgStmt("list_delete_all", {"name": handle.name})
    if name == "insert_at_list" and len(node.args) == 3:
        handle = _require_list_handle(node.args[0], context)
        return CgStmt(
            "list_insert",
            {"name": handle.name, "index": lower_expr(node.args[1], context), "item": lower_expr(node.args[2], context)},
        )
    if name == "replace_in_list" and len(node.args) == 3:
        handle = _require_list_handle(node.args[0], context)
        return CgStmt(
            "list_replace",
            {"name": handle.name, "index": lower_expr(node.args[1], context), "item": lower_expr(node.args[2], context)},
        )
    args = [lower_expr(arg, context) for arg in node.args]
    if name == "wait" and len(args) == 1:
        return CgStmt("wait", {"duration": args[0]})
    if name == "broadcast" and len(args) == 1:
        literal = _require_string_literal(node.args[0], context)
        context.project.register_broadcast(literal)
        return CgStmt("broadcast", {"name": literal, "wait": False})
    if name == "broadcast_wait" and len(args) == 1:
        literal = _require_string_literal(node.args[0], context)
        context.project.register_broadcast(literal)
        return CgStmt("broadcast", {"name": literal, "wait": True})
    if name == "goto_xy" and len(args) == 2:
        return CgStmt("move_state", {"mode": "goto_xy", "x": args[0], "y": args[1]})
    if name == "goto_target" and len(args) == 1:
        return CgStmt("move_state", {"mode": "goto_target", "target": args[0]})
    if name == "glide_xy" and len(args) == 3:
        return CgStmt("move_state", {"mode": "glide_xy", "duration": args[0], "x": args[1], "y": args[2]})
    if name == "glide_to" and len(args) == 2:
        return CgStmt("move_state", {"mode": "glide_target", "duration": args[0], "target": args[1]})
    if name == "set_x" and len(args) == 1:
        return CgStmt("move_state", {"mode": "set_x", "x": args[0]})
    if name == "set_y" and len(args) == 1:
        return CgStmt("move_state", {"mode": "set_y", "y": args[0]})
    if name == "change_x_by" and len(args) == 1:
        return CgStmt("move_state", {"mode": "change_x", "dx": args[0]})
    if name == "change_y_by" and len(args) == 1:
        return CgStmt("move_state", {"mode": "change_y", "dy": args[0]})
    if name == "turn_right" and len(args) == 1:
        return CgStmt("move_state", {"mode": "turn_right", "degrees": args[0]})
    if name == "turn_left" and len(args) == 1:
        return CgStmt("move_state", {"mode": "turn_left", "degrees": args[0]})
    if name == "point_in_direction" and len(args) == 1:
        return CgStmt("move_state", {"mode": "point_direction", "direction": args[0]})
    if name == "point_towards" and len(args) == 1:
        return CgStmt("move_state", {"mode": "point_towards", "target": args[0]})
    if name == "set_rotation_style" and len(node.args) == 1:
        return CgStmt("move_state", {"mode": "set_rotation_style", "style": _require_string_literal(node.args[0], context)})
    if name == "hide" and not args:
        return CgStmt("looks_state", {"mode": "hide"})
    if name == "show" and not args:
        return CgStmt("looks_state", {"mode": "show"})
    if name == "say" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "dialogue", "style": "say", "message": args[0]})
    if name == "say_for_secs" and len(args) == 2:
        return CgStmt("looks_state", {"mode": "dialogue", "style": "say", "message": args[0], "duration": args[1]})
    if name == "think" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "dialogue", "style": "think", "message": args[0]})
    if name == "think_for_secs" and len(args) == 2:
        return CgStmt("looks_state", {"mode": "dialogue", "style": "think", "message": args[0], "duration": args[1]})
    if name == "switch_costume" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "switch_costume", "costume": args[0]})
    if name == "next_costume" and not args:
        return CgStmt("looks_state", {"mode": "next_costume"})
    if name == "switch_backdrop" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "switch_backdrop", "backdrop": args[0], "wait": False})
    if name == "switch_backdrop_wait" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "switch_backdrop", "backdrop": args[0], "wait": True})
    if name == "next_backdrop" and not args:
        return CgStmt("looks_state", {"mode": "next_backdrop"})
    if name == "set_size" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "set_size", "size": args[0]})
    if name == "change_size_by" and len(args) == 1:
        return CgStmt("looks_state", {"mode": "change_size", "delta": args[0]})
    if name == "set_effect" and len(args) == 2:
        return CgStmt("looks_state", {"mode": "set_effect", "effect": _require_string_literal(node.args[0], context), "value": args[1]})
    if name == "change_effect_by" and len(args) == 2:
        return CgStmt("looks_state", {"mode": "change_effect", "effect": _require_string_literal(node.args[0], context), "value": args[1]})
    if name == "clear_graphic_effects" and not args:
        return CgStmt("looks_state", {"mode": "clear_effects"})
    if name == "go_front_back" and len(node.args) == 1:
        return CgStmt("looks_state", {"mode": "go_front_back", "direction": _require_string_literal(node.args[0], context)})
    if name == "go_layers" and len(node.args) == 2:
        return CgStmt("looks_state", {"mode": "go_layers", "direction": _require_string_literal(node.args[0], context), "layers": args[1]})
    if name == "create_clone" and len(node.args) == 1:
        return CgStmt("create_clone", {"selector": args[0]})
    if name == "delete_this_clone" and not args:
        return CgStmt("delete_clone", {})
    if name == "ask" and len(args) == 1:
        return CgStmt("ask", {"prompt": args[0]})
    if name == "reset_timer" and not args:
        return CgStmt("reset_timer", {})
    if name == "play_note_for_beats" and len(args) == 2:
        return CgStmt("music_play_note", {"note": args[0], "beats": args[1]})
    if name == "stop" and len(node.args) == 1:
        return CgStmt("stop", {"mode": _require_string_literal(node.args[0], context)})
    if name in context.procedures:
        proc = context.procedures[name]
        if proc.target_name != context.target.name:
            raise CodegenError("Procedures can only be called within the same target in v1")
        fn_node = get_function_ast(proc.function)
        if len(node.args) != len(fn_node.args.args):
            raise CodegenError(f"Procedure {name} argument count mismatch")
        arg_names = _binding_argument_names(proc, tuple(arg.arg for arg in fn_node.args.args))
        arg_ids = {f"arg:{name}:{index}": lower_expr(arg, context) for index, arg in enumerate(node.args)}
        return CgStmt("proc_call", {"proccode": proc.proccode or _procedure_proccode(name, arg_names), "arguments": arg_ids})
    raise CodegenError(f"Unsupported call in statement position: {name}")


def lower_expr(node: ast.AST, context: CompileContext) -> CgExpr:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return CgExpr("literal", "true" if node.value else "false")
        return CgExpr("literal", node.value)
    if isinstance(node, (ast.Name, ast.Attribute)):
        if isinstance(node, ast.Name) and node.id in context.parameters:
            return CgExpr("proc_arg", context.parameter_display_names.get(node.id, node.id))
        handle = _resolve_static_object(node, context)
        if isinstance(handle, VariableHandle):
            return CgExpr("var", handle.name)
        if isinstance(handle, ListHandle):
            raise CodegenError("Lists cannot be used directly as expressions; use explicit list intrinsics/reporters")
        if isinstance(handle, (ScratchConstant, ScratchEnum)):
            return CgExpr("literal", handle.value)
        label = ast.unparse(node)
        raise CodegenError(f"Unknown name in authoring expression: {label}")
    if isinstance(node, ast.BinOp):
        op_map = {
            ast.Add: "operator_add",
            ast.Sub: "operator_subtract",
            ast.Mult: "operator_multiply",
            ast.Div: "operator_divide",
            ast.Mod: "operator_mod",
        }
        for op_type, kind in op_map.items():
            if isinstance(node.op, op_type):
                return CgExpr(kind, args=(lower_expr(node.left, context), lower_expr(node.right, context)))
        raise CodegenError("Unsupported binary operator")
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return CgExpr("operator_not", args=(lower_expr(node.operand, context),))
        if isinstance(node.op, ast.USub):
            operand = lower_expr(node.operand, context)
            if operand.kind == "literal" and isinstance(operand.value, (int, float)):
                return CgExpr("literal", -operand.value)
            return CgExpr("operator_subtract", args=(CgExpr("literal", 0), operand))
    if isinstance(node, ast.BoolOp):
        if len(node.values) != 2:
            raise CodegenError("Boolean expressions are limited to two operands")
        kind = "operator_and" if isinstance(node.op, ast.And) else "operator_or"
        return CgExpr(kind, args=(lower_expr(node.values[0], context), lower_expr(node.values[1], context)))
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise CodegenError("Only simple comparisons are supported")
        op = node.ops[0]
        kind_map = {
            ast.Eq: "operator_equals",
            ast.Lt: "operator_lt",
            ast.Gt: "operator_gt",
        }
        for op_type, kind in kind_map.items():
            if isinstance(op, op_type):
                return CgExpr(kind, args=(lower_expr(node.left, context), lower_expr(node.comparators[0], context)))
        raise CodegenError("Unsupported comparison operator")
    if isinstance(node, ast.Call):
        method = _resolve_method_receiver(node.func, context)
        if method is not None:
            receiver, name = method
            if isinstance(receiver, ListHandle):
                if name == "item" and len(node.args) == 1:
                    return CgExpr("list_item", {"name": receiver.name, "index": lower_expr(node.args[0], context)})
                if name == "length" and not node.args:
                    return CgExpr("list_length", receiver.name)
                if name == "contains" and len(node.args) == 1:
                    return CgExpr("list_contains", {"name": receiver.name, "item": lower_expr(node.args[0], context)})
                if name == "contents" and not node.args:
                    return CgExpr("list_contents", receiver.name)
            if isinstance(receiver, VariableHandle):
                if name == "value" and not node.args:
                    return CgExpr("var", receiver.name)
            if isinstance(receiver, TargetBuilder):
                _require_current_target_receiver(receiver, context)
                if name == "touching_object" and len(node.args) == 1:
                    return CgExpr("touching_object", args=(lower_expr(node.args[0], context),))
                if name == "x_position" and not node.args:
                    return CgExpr("x_position")
                if name == "y_position" and not node.args:
                    return CgExpr("y_position")
                if name == "direction_value" and not node.args:
                    return CgExpr("direction")
                if name == "size_value" and not node.args:
                    return CgExpr("size")
                if name == "costume_number" and not node.args:
                    return CgExpr("costume_info", "number")
                if name == "costume_name" and not node.args:
                    return CgExpr("costume_info", "name")
                if name == "backdrop_number" and not node.args:
                    return CgExpr("backdrop_info", "number")
                if name == "backdrop_name" and not node.args:
                    return CgExpr("backdrop_info", "name")
            raise CodegenError(f"Unsupported method call in authoring expressions: {ast.unparse(node.func)}")
        if not isinstance(node.func, ast.Name):
            raise CodegenError("Only direct function calls are supported in expressions")
        name = node.func.id
        if name == "list_item" and len(node.args) == 2:
            handle = _require_list_handle(node.args[0], context)
            return CgExpr("list_item", {"name": handle.name, "index": lower_expr(node.args[1], context)})
        if name == "list_length" and len(node.args) == 1:
            handle = _require_list_handle(node.args[0], context)
            return CgExpr("list_length", handle.name)
        if name == "list_contains" and len(node.args) == 2:
            handle = _require_list_handle(node.args[0], context)
            return CgExpr("list_contains", {"name": handle.name, "item": lower_expr(node.args[1], context)})
        if name == "list_contents" and len(node.args) == 1:
            handle = _require_list_handle(node.args[0], context)
            return CgExpr("list_contents", handle.name)
        args = tuple(lower_expr(arg, context) for arg in node.args)
        if name == "timer" and not args:
            return CgExpr("timer")
        if name == "answer" and not args:
            return CgExpr("answer")
        if name == "key_pressed" and len(args) == 1:
            return CgExpr("key_pressed", args=args)
        if name == "mouse_x" and not args:
            return CgExpr("mouse_x")
        if name == "mouse_y" and not args:
            return CgExpr("mouse_y")
        if name == "mouse_down" and not args:
            return CgExpr("mouse_down")
        if name == "touching_object" and len(args) == 1:
            return CgExpr("touching_object", args=args)
        if name == "x_position" and not args:
            return CgExpr("x_position")
        if name == "y_position" and not args:
            return CgExpr("y_position")
        if name == "direction" and not args:
            return CgExpr("direction")
        if name == "size" and not args:
            return CgExpr("size")
        if name == "costume_number" and not args:
            return CgExpr("costume_info", "number")
        if name == "costume_name" and not args:
            return CgExpr("costume_info", "name")
        if name == "backdrop_number" and not args:
            return CgExpr("backdrop_info", "number")
        if name == "backdrop_name" and not args:
            return CgExpr("backdrop_info", "name")
        if name == "join" and len(args) == 2:
            return CgExpr("operator_join", args=args)
        if name == "letter_of" and len(args) == 2:
            return CgExpr("operator_letter_of", args=args)
        if name == "string_length" and len(args) == 1:
            return CgExpr("operator_length", args=args)
        if name == "string_contains" and len(args) == 2:
            return CgExpr("operator_contains", args=args)
        if name == "round_value" and len(args) == 1:
            return CgExpr("operator_round", args=args)
        if name == "math_op" and len(args) == 2:
            literal = _require_string_literal(node.args[0], context)
            return CgExpr("operator_mathop", value=literal, args=(args[1],))
        if name == "random_between" and len(args) == 2:
            return CgExpr("operator_random", args=args)
        raise CodegenError(f"Unsupported call in expression position: {name}")
    raise CodegenError(f"Unsupported expression syntax: {node.__class__.__name__}")


def _resolve_variable(name: str, context: CompileContext) -> VariableHandle:
    handle = context.module_globals.get(name)
    if not isinstance(handle, VariableHandle):
        raise CodegenError(f"{name!r} is not a declared Scratch variable")
    return handle


def _require_list_handle(node: ast.AST, context: CompileContext) -> ListHandle:
    if not isinstance(node, ast.Name):
        raise CodegenError("List intrinsics require a declared list handle as the first argument")
    handle = context.module_globals.get(node.id)
    if not isinstance(handle, ListHandle):
        raise CodegenError(f"{node.id!r} is not a declared Scratch list")
    return handle


def _require_string_literal(node: ast.AST, context: CompileContext) -> str:
    resolved = _resolve_static_object(node, context)
    if isinstance(resolved, (ScratchConstant, ScratchEnum)):
        return str(resolved.value)
    expr = lower_expr(node, context)
    if expr.kind != "literal" or not isinstance(expr.value, str):
        raise CodegenError("This intrinsic requires a literal string argument in v1")
    return expr.value


def _procedure_proccode(name: str, arguments: tuple[str, ...]) -> str:
    return " ".join([name, *(["%s"] * len(arguments))]).strip()


def _binding_argument_names(binding: ProcedureBinding, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if binding.argument_names is None:
        return fallback
    if len(binding.argument_names) != len(fallback):
        raise CodegenError("Procedure argument_names length does not match the function signature")
    return tuple(binding.argument_names)


def _binding_argument_defaults(binding: ProcedureBinding, count: int) -> tuple[Any, ...]:
    if binding.argument_defaults is None:
        return tuple("" for _ in range(count))
    if len(binding.argument_defaults) != count:
        raise CodegenError("Procedure argument_defaults length does not match the function signature")
    return tuple(binding.argument_defaults)


class _BlockEmitter:
    def __init__(self, target: CgTarget, *, broadcasts: dict[str, str], variable_ids: dict[tuple[str, str], str], list_ids: dict[tuple[str, str], str]) -> None:
        self.target = target
        self.broadcasts = broadcasts
        self.variable_ids = variable_ids
        self.list_ids = list_ids
        self.blocks: dict[str, dict[str, Any]] = {}
        self.counter = 0

    def _variable_id(self, name: str) -> str:
        variable_id = self.variable_ids.get((self.target.name, name))
        if variable_id is not None:
            return variable_id
        variable_id = self.variable_ids.get(("Stage", name))
        if variable_id is not None:
            return variable_id
        raise CodegenError(f"Unknown variable {name!r} on target {self.target.name!r}")

    def _list_id(self, name: str) -> str:
        list_id = self.list_ids.get((self.target.name, name))
        if list_id is not None:
            return list_id
        list_id = self.list_ids.get(("Stage", name))
        if list_id is not None:
            return list_id
        raise CodegenError(f"Unknown list {name!r} on target {self.target.name!r}")

    def new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{self.target.name}:{prefix}:{self.counter}"

    def emit_scripts(self) -> dict[str, dict[str, Any]]:
        for procedure in self.target.procedures:
            self._emit_procedure(procedure)
        for script in self.target.scripts:
            self._emit_script(script)
        return self.blocks

    def _emit_script(self, script: CgScript) -> None:
        hat_id = self.new_id("hat")
        if script.trigger_kind == "green_flag":
            opcode = "event_whenflagclicked"
            fields: dict[str, Any] = {}
        elif script.trigger_kind == "key_pressed":
            opcode = "event_whenkeypressed"
            fields = {"KEY_OPTION": [script.trigger_value or "", None]}
        elif script.trigger_kind == "backdrop_switched":
            opcode = "event_whenbackdropswitchesto"
            fields = {"BACKDROP": [script.trigger_value or "", None]}
        elif script.trigger_kind == "broadcast_received":
            opcode = "event_whenbroadcastreceived"
            fields = {"BROADCAST_OPTION": [script.trigger_value, self.broadcasts[script.trigger_value]]}
        elif script.trigger_kind == "clone_start":
            opcode = "control_start_as_clone"
            fields = {}
        else:
            raise CodegenError(f"Unsupported trigger kind {script.trigger_kind!r}")
        self.blocks[hat_id] = {
            "opcode": opcode,
            "next": None,
            "parent": None,
            "inputs": {},
            "fields": fields,
            "topLevel": True,
        }
        first = self._emit_stmt_chain(script.body, parent=hat_id)
        self.blocks[hat_id]["next"] = first

    def _emit_procedure(self, procedure: CgProcedure) -> None:
        def_id = self.new_id("procdef")
        proto_id = self.new_id("prototype")
        self.blocks[def_id] = {
            "opcode": "procedures_definition",
            "next": None,
            "parent": None,
            "inputs": {"custom_block": [1, proto_id]},
            "fields": {},
            "topLevel": True,
        }
        self.blocks[proto_id] = {
            "opcode": "procedures_prototype",
            "next": None,
            "parent": def_id,
            "inputs": {},
            "fields": {},
            "topLevel": False,
            "mutation": {
                "proccode": procedure.proccode,
                "argumentids": json.dumps(list(procedure.argument_ids)),
                "argumentnames": json.dumps(list(procedure.argument_names)),
                "argumentdefaults": json.dumps(list(procedure.argument_defaults)),
                "warp": "true" if procedure.warp else "false",
            },
        }
        self.blocks[def_id]["next"] = self._emit_stmt_chain(procedure.body, parent=def_id, procedure=procedure)

    def _emit_stmt_chain(self, body: tuple[CgStmt, ...], *, parent: str, procedure: CgProcedure | None = None) -> str | None:
        first_id: str | None = None
        prev_id: str | None = None
        for stmt in body:
            block_id = self._emit_stmt(stmt, parent=prev_id or parent, procedure=procedure)
            if first_id is None:
                first_id = block_id
            if prev_id is not None:
                self.blocks[prev_id]["next"] = block_id
            prev_id = block_id
        return first_id

    def _emit_stmt(self, stmt: CgStmt, *, parent: str, procedure: CgProcedure | None) -> str:
        block_id = self.new_id(stmt.kind)
        payload = {"next": None, "parent": parent, "inputs": {}, "fields": {}, "topLevel": False}
        if stmt.kind == "set_var":
            payload["opcode"] = "data_setvariableto"
            payload["inputs"]["VALUE"] = self._expr_input(stmt.args["value"], parent=block_id, procedure=procedure)
            payload["fields"]["VARIABLE"] = [stmt.args["name"], self._variable_id(stmt.args["name"]) ]
        elif stmt.kind == "change_var":
            payload["opcode"] = "data_changevariableby"
            payload["inputs"]["VALUE"] = self._expr_input(stmt.args["value"], parent=block_id, procedure=procedure)
            payload["fields"]["VARIABLE"] = [stmt.args["name"], self._variable_id(stmt.args["name"]) ]
        elif stmt.kind == "wait":
            payload["opcode"] = "control_wait"
            payload["inputs"]["DURATION"] = self._expr_input(stmt.args["duration"], parent=block_id, procedure=procedure)
        elif stmt.kind == "broadcast":
            payload["opcode"] = "event_broadcastandwait" if stmt.args["wait"] else "event_broadcast"
            payload["inputs"]["BROADCAST_INPUT"] = [1, [10, stmt.args["name"]]]
        elif stmt.kind == "repeat":
            payload["opcode"] = "control_repeat"
            payload["inputs"]["TIMES"] = self._expr_input(stmt.args["times"], parent=block_id, procedure=procedure)
            first = self._emit_stmt_chain(stmt.args["body"], parent=block_id, procedure=procedure)
            if first is not None:
                payload["inputs"]["SUBSTACK"] = [2, first]
        elif stmt.kind == "forever":
            payload["opcode"] = "control_forever"
            first = self._emit_stmt_chain(stmt.args["body"], parent=block_id, procedure=procedure)
            if first is not None:
                payload["inputs"]["SUBSTACK"] = [2, first]
        elif stmt.kind == "repeat_until":
            payload["opcode"] = "control_repeat_until"
            payload["inputs"]["CONDITION"] = self._expr_input(stmt.args["condition"], parent=block_id, procedure=procedure)
            first = self._emit_stmt_chain(stmt.args["body"], parent=block_id, procedure=procedure)
            if first is not None:
                payload["inputs"]["SUBSTACK"] = [2, first]
        elif stmt.kind in {"if", "if_else"}:
            payload["opcode"] = "control_if_else" if stmt.kind == "if_else" else "control_if"
            payload["inputs"]["CONDITION"] = self._expr_input(stmt.args["condition"], parent=block_id, procedure=procedure)
            first = self._emit_stmt_chain(stmt.args["body"], parent=block_id, procedure=procedure)
            if first is not None:
                payload["inputs"]["SUBSTACK"] = [2, first]
            if stmt.kind == "if_else":
                other = self._emit_stmt_chain(stmt.args["else_body"], parent=block_id, procedure=procedure)
                if other is not None:
                    payload["inputs"]["SUBSTACK2"] = [2, other]
        elif stmt.kind == "stop":
            payload["opcode"] = "control_stop"
            payload["fields"]["STOP_OPTION"] = [stmt.args["mode"], None]
        elif stmt.kind == "list_add":
            payload["opcode"] = "data_addtolist"
            payload["inputs"]["ITEM"] = self._expr_input(stmt.args["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self._list_id(stmt.args["name"]) ]
        elif stmt.kind == "list_delete":
            payload["opcode"] = "data_deleteoflist"
            payload["inputs"]["INDEX"] = self._expr_input(stmt.args["index"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self._list_id(stmt.args["name"]) ]
        elif stmt.kind == "list_delete_all":
            payload["opcode"] = "data_deletealloflist"
            payload["fields"]["LIST"] = [stmt.args["name"], self._list_id(stmt.args["name"]) ]
        elif stmt.kind == "list_insert":
            payload["opcode"] = "data_insertatlist"
            payload["inputs"]["INDEX"] = self._expr_input(stmt.args["index"], parent=block_id, procedure=procedure)
            payload["inputs"]["ITEM"] = self._expr_input(stmt.args["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self._list_id(stmt.args["name"]) ]
        elif stmt.kind == "list_replace":
            payload["opcode"] = "data_replaceitemoflist"
            payload["inputs"]["INDEX"] = self._expr_input(stmt.args["index"], parent=block_id, procedure=procedure)
            payload["inputs"]["ITEM"] = self._expr_input(stmt.args["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self._list_id(stmt.args["name"]) ]
        elif stmt.kind == "move_state":
            mode = stmt.args["mode"]
            if mode == "goto_xy":
                payload["opcode"] = "motion_gotoxy"
                payload["inputs"]["X"] = self._expr_input(stmt.args["x"], parent=block_id, procedure=procedure)
                payload["inputs"]["Y"] = self._expr_input(stmt.args["y"], parent=block_id, procedure=procedure)
            elif mode == "goto_target":
                payload["opcode"] = "motion_goto"
                payload["inputs"]["TO"] = self._expr_input(stmt.args["target"], parent=block_id, procedure=procedure)
            elif mode == "glide_xy":
                payload["opcode"] = "motion_glidesecstoxy"
                payload["inputs"]["SECS"] = self._expr_input(stmt.args["duration"], parent=block_id, procedure=procedure)
                payload["inputs"]["X"] = self._expr_input(stmt.args["x"], parent=block_id, procedure=procedure)
                payload["inputs"]["Y"] = self._expr_input(stmt.args["y"], parent=block_id, procedure=procedure)
            elif mode == "glide_target":
                payload["opcode"] = "motion_glideto"
                payload["inputs"]["SECS"] = self._expr_input(stmt.args["duration"], parent=block_id, procedure=procedure)
                payload["inputs"]["TO"] = self._expr_input(stmt.args["target"], parent=block_id, procedure=procedure)
            elif mode == "set_x":
                payload["opcode"] = "motion_setx"
                payload["inputs"]["X"] = self._expr_input(stmt.args["x"], parent=block_id, procedure=procedure)
            elif mode == "set_y":
                payload["opcode"] = "motion_sety"
                payload["inputs"]["Y"] = self._expr_input(stmt.args["y"], parent=block_id, procedure=procedure)
            elif mode == "change_x":
                payload["opcode"] = "motion_changexby"
                payload["inputs"]["DX"] = self._expr_input(stmt.args["dx"], parent=block_id, procedure=procedure)
            elif mode == "change_y":
                payload["opcode"] = "motion_changeyby"
                payload["inputs"]["DY"] = self._expr_input(stmt.args["dy"], parent=block_id, procedure=procedure)
            elif mode == "turn_right":
                payload["opcode"] = "motion_turnright"
                payload["inputs"]["DEGREES"] = self._expr_input(stmt.args["degrees"], parent=block_id, procedure=procedure)
            elif mode == "turn_left":
                payload["opcode"] = "motion_turnleft"
                payload["inputs"]["DEGREES"] = self._expr_input(stmt.args["degrees"], parent=block_id, procedure=procedure)
            elif mode == "point_direction":
                payload["opcode"] = "motion_pointindirection"
                payload["inputs"]["DIRECTION"] = self._expr_input(stmt.args["direction"], parent=block_id, procedure=procedure)
            elif mode == "point_towards":
                payload["opcode"] = "motion_pointtowards"
                payload["inputs"]["TOWARDS"] = self._expr_input(stmt.args["target"], parent=block_id, procedure=procedure)
            elif mode == "set_rotation_style":
                payload["opcode"] = "motion_setrotationstyle"
                payload["fields"]["STYLE"] = [stmt.args["style"], None]
            else:
                raise CodegenError(f"Unsupported movement mode {mode!r}")
        elif stmt.kind == "looks_state":
            mode = stmt.args["mode"]
            if mode == "hide":
                payload["opcode"] = "looks_hide"
            elif mode == "show":
                payload["opcode"] = "looks_show"
            elif mode == "dialogue":
                has_duration = "duration" in stmt.args
                payload["opcode"] = {
                    ("say", False): "looks_say",
                    ("say", True): "looks_sayforsecs",
                    ("think", False): "looks_think",
                    ("think", True): "looks_thinkforsecs",
                }[(stmt.args["style"], has_duration)]
                payload["inputs"]["MESSAGE"] = self._expr_input(stmt.args["message"], parent=block_id, procedure=procedure)
                if has_duration:
                    payload["inputs"]["SECS"] = self._expr_input(stmt.args["duration"], parent=block_id, procedure=procedure)
            elif mode == "switch_costume":
                payload["opcode"] = "looks_switchcostumeto"
                payload["inputs"]["COSTUME"] = self._expr_input(stmt.args["costume"], parent=block_id, procedure=procedure)
            elif mode == "next_costume":
                payload["opcode"] = "looks_nextcostume"
            elif mode == "switch_backdrop":
                payload["opcode"] = "looks_switchbackdroptoandwait" if stmt.args["wait"] else "looks_switchbackdropto"
                payload["inputs"]["BACKDROP"] = self._expr_input(stmt.args["backdrop"], parent=block_id, procedure=procedure)
            elif mode == "next_backdrop":
                payload["opcode"] = "looks_nextbackdrop"
            elif mode == "set_size":
                payload["opcode"] = "looks_setsizeto"
                payload["inputs"]["SIZE"] = self._expr_input(stmt.args["size"], parent=block_id, procedure=procedure)
            elif mode == "change_size":
                payload["opcode"] = "looks_changesizeby"
                payload["inputs"]["CHANGE"] = self._expr_input(stmt.args["delta"], parent=block_id, procedure=procedure)
            elif mode == "set_effect":
                payload["opcode"] = "looks_seteffectto"
                payload["fields"]["EFFECT"] = [stmt.args["effect"], None]
                payload["inputs"]["VALUE"] = self._expr_input(stmt.args["value"], parent=block_id, procedure=procedure)
            elif mode == "change_effect":
                payload["opcode"] = "looks_changeeffectby"
                payload["fields"]["EFFECT"] = [stmt.args["effect"], None]
                payload["inputs"]["CHANGE"] = self._expr_input(stmt.args["value"], parent=block_id, procedure=procedure)
            elif mode == "clear_effects":
                payload["opcode"] = "looks_cleargraphiceffects"
            elif mode == "go_front_back":
                payload["opcode"] = "looks_gotofrontback"
                payload["fields"]["FRONT_BACK"] = [stmt.args["direction"], None]
            elif mode == "go_layers":
                payload["opcode"] = "looks_goforwardbackwardlayers"
                payload["fields"]["FORWARD_BACKWARD"] = [stmt.args["direction"], None]
                payload["inputs"]["NUM"] = self._expr_input(stmt.args["layers"], parent=block_id, procedure=procedure)
            else:
                raise CodegenError(f"Unsupported looks mode {mode!r}")
        elif stmt.kind == "create_clone":
            payload["opcode"] = "control_create_clone_of"
            payload["inputs"]["CLONE_OPTION"] = self._expr_input(stmt.args["selector"], parent=block_id, procedure=procedure)
        elif stmt.kind == "delete_clone":
            payload["opcode"] = "control_delete_this_clone"
        elif stmt.kind == "ask":
            payload["opcode"] = "sensing_askandwait"
            payload["inputs"]["QUESTION"] = self._expr_input(stmt.args["prompt"], parent=block_id, procedure=procedure)
        elif stmt.kind == "reset_timer":
            payload["opcode"] = "sensing_resettimer"
        elif stmt.kind == "music_play_note":
            payload["opcode"] = "music_playNoteForBeats"
            payload["inputs"]["NOTE"] = self._expr_input(stmt.args["note"], parent=block_id, procedure=procedure)
            payload["inputs"]["BEATS"] = self._expr_input(stmt.args["beats"], parent=block_id, procedure=procedure)
        elif stmt.kind == "proc_call":
            payload["opcode"] = "procedures_call"
            payload["mutation"] = {"proccode": stmt.args["proccode"]}
            for arg_id, expr in stmt.args["arguments"].items():
                payload["inputs"][arg_id] = self._expr_input(expr, parent=block_id, procedure=procedure)
        else:
            raise CodegenError(f"Unsupported codegen statement kind {stmt.kind!r}")
        self.blocks[block_id] = payload
        return block_id

    def _expr_input(self, expr: CgExpr, *, parent: str, procedure: CgProcedure | None) -> list[Any]:
        if expr.kind == "literal":
            return [1, _literal_payload(expr.value)]
        return [3, self._emit_expr(expr, parent=parent, procedure=procedure)]

    def _emit_expr(self, expr: CgExpr, *, parent: str, procedure: CgProcedure | None) -> str:
        block_id = self.new_id(expr.kind)
        payload = {"next": None, "parent": parent, "inputs": {}, "fields": {}, "topLevel": False}
        if expr.kind == "var":
            payload["opcode"] = "data_variable"
            payload["fields"]["VARIABLE"] = [expr.value, self._variable_id(expr.value) ]
        elif expr.kind == "proc_arg":
            if procedure is None:
                raise CodegenError("Procedure arguments can only be used inside procedures")
            payload["opcode"] = "argument_reporter_string_number"
            payload["fields"]["VALUE"] = [expr.value, None]
        elif expr.kind == "list_item":
            payload["opcode"] = "data_itemoflist"
            payload["inputs"]["INDEX"] = self._expr_input(expr.value["index"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [expr.value["name"], self._list_id(expr.value["name"]) ]
        elif expr.kind == "list_length":
            payload["opcode"] = "data_lengthoflist"
            payload["fields"]["LIST"] = [expr.value, self._list_id(expr.value) ]
        elif expr.kind == "list_contains":
            payload["opcode"] = "data_listcontainsitem"
            payload["inputs"]["ITEM"] = self._expr_input(expr.value["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [expr.value["name"], self._list_id(expr.value["name"]) ]
        elif expr.kind == "list_contents":
            payload["opcode"] = "data_contentsoflist"
            payload["fields"]["LIST"] = [expr.value, self._list_id(expr.value) ]
        elif expr.kind in {"operator_add", "operator_subtract", "operator_multiply", "operator_divide", "operator_mod"}:
            payload["opcode"] = expr.kind
            payload["inputs"]["NUM1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["NUM2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind in {"operator_equals", "operator_lt", "operator_gt"}:
            payload["opcode"] = expr.kind
            payload["inputs"]["OPERAND1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["OPERAND2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind in {"operator_and", "operator_or"}:
            payload["opcode"] = expr.kind
            payload["inputs"]["OPERAND1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["OPERAND2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_not":
            payload["opcode"] = "operator_not"
            payload["inputs"]["OPERAND"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_join":
            payload["opcode"] = "operator_join"
            payload["inputs"]["STRING1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["STRING2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_contains":
            payload["opcode"] = "operator_contains"
            payload["inputs"]["STRING1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["STRING2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_letter_of":
            payload["opcode"] = "operator_letter_of"
            payload["inputs"]["LETTER"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["STRING"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_length":
            payload["opcode"] = "operator_length"
            payload["inputs"]["STRING"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_round":
            payload["opcode"] = "operator_round"
            payload["inputs"]["NUM"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_mathop":
            payload["opcode"] = "operator_mathop"
            payload["fields"]["OPERATOR"] = [expr.value, None]
            payload["inputs"]["NUM"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "timer":
            payload["opcode"] = "sensing_timer"
        elif expr.kind == "answer":
            payload["opcode"] = "sensing_answer"
        elif expr.kind == "key_pressed":
            payload["opcode"] = "sensing_keypressed"
            payload["inputs"]["KEY_OPTION"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "mouse_x":
            payload["opcode"] = "sensing_mousex"
        elif expr.kind == "mouse_y":
            payload["opcode"] = "sensing_mousey"
        elif expr.kind == "mouse_down":
            payload["opcode"] = "sensing_mousedown"
        elif expr.kind == "touching_object":
            payload["opcode"] = "sensing_touchingobject"
            payload["inputs"]["TOUCHINGOBJECTMENU"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "x_position":
            payload["opcode"] = "motion_xposition"
        elif expr.kind == "y_position":
            payload["opcode"] = "motion_yposition"
        elif expr.kind == "direction":
            payload["opcode"] = "motion_direction"
        elif expr.kind == "size":
            payload["opcode"] = "looks_size"
        elif expr.kind == "costume_info":
            payload["opcode"] = "looks_costumenumbername"
            payload["fields"]["NUMBER_NAME"] = [expr.value, None]
        elif expr.kind == "backdrop_info":
            payload["opcode"] = "looks_backdropnumbername"
            payload["fields"]["NUMBER_NAME"] = [expr.value, None]
        elif expr.kind == "operator_random":
            payload["opcode"] = "operator_random"
            payload["inputs"]["FROM"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["TO"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        else:
            raise CodegenError(f"Unsupported codegen expression kind {expr.kind!r}")
        self.blocks[block_id] = payload
        return block_id


def emit_project(project: CgProject) -> Project:
    variable_ids: dict[tuple[str, str], str] = {}
    list_ids: dict[tuple[str, str], str] = {}
    broadcasts = {name: f"broadcast:{index}" for index, name in enumerate(project.broadcasts, start=1)}
    for target in project.targets:
        for index, (name, _) in enumerate(target.variables, start=1):
            variable_ids[(target.name, name)] = f"var:{target.name}:{index}"
        for index, (name, _) in enumerate(target.lists, start=1):
            list_ids[(target.name, name)] = f"list:{target.name}:{index}"

    targets_json: list[dict[str, Any]] = []
    for target in project.targets:
        emitter = _BlockEmitter(target, broadcasts=broadcasts, variable_ids=variable_ids, list_ids=list_ids)
        blocks = emitter.emit_scripts()
        target_json: dict[str, Any] = {
            "isStage": target.is_stage,
            "name": target.name,
            "variables": {variable_ids[(target.name, name)]: [name, default] for name, default in target.variables},
            "lists": {list_ids[(target.name, name)]: [name, list(values)] for name, values in target.lists},
            "broadcasts": broadcasts if target.is_stage else {},
            "blocks": blocks,
            "comments": {},
            "costumes": list(target.costumes),
            "sounds": list(target.sounds),
            "currentCostume": target.current_costume,
            "volume": target.volume,
            "layerOrder": target.layer_order,
            "tempo": target.tempo,
            "videoTransparency": target.video_transparency,
            "videoState": target.video_state,
            "textToSpeechLanguage": target.text_to_speech_language,
            "x": target.x,
            "y": target.y,
            "direction": target.direction,
            "size": target.size,
            "visible": target.visible,
            "draggable": target.draggable,
            "rotationStyle": target.rotation_style,
        }
        targets_json.append(target_json)

    return Project.from_json(
        {
            "targets": targets_json,
            "monitors": [],
            "extensions": list(project.extensions),
            "meta": {"semver": "3.0.0", "vm": project.name},
        },
        assets=dict(project.assets),
    )


def save_authored_project(source: str | Path | ModuleType, output: str | Path, *, project_attr: str = "project") -> Project:
    project = build_project(source, project_attr=project_attr)
    save_sb3(project, output)
    return project


def _literal_payload(value: Any) -> list[Any]:
    if value is None:
        return [10, ""]
    if isinstance(value, (int, float)):
        return [4, str(value)]
    return [10, str(value)]

