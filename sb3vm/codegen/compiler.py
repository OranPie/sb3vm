from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from sb3vm.codegen.api import ListHandle, ProcedureBinding, ScratchProject, TargetBuilder, VariableHandle
from sb3vm.codegen.ir import CgExpr, CgProcedure, CgProject, CgScript, CgStmt, CgTarget
from sb3vm.io.save_sb3 import save_sb3
from sb3vm.model.project import Project
from sb3vm.vm.errors import Sb3VmError
from sb3vm.vm.runtime import Sb3Vm


class CodegenError(Sb3VmError):
    pass


def load_authoring_module(path: str | Path) -> ModuleType:
    source_path = Path(path)
    module_name = f"sb3vm_codegen_{source_path.stem}_{abs(hash(source_path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise CodegenError(f"Unable to load authoring module: {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_authoring_project(module: ModuleType, attr: str = "project") -> ScratchProject:
    candidate = getattr(module, attr, None)
    if not isinstance(candidate, ScratchProject):
        raise CodegenError(f"Authoring module is missing ScratchProject attribute {attr!r}")
    return candidate


def build_project(source: str | Path | ModuleType, *, project_attr: str = "project") -> Project:
    module = load_authoring_module(source) if not isinstance(source, ModuleType) else source
    authoring = get_authoring_project(module, project_attr)
    ir_project = lower_authoring_project(authoring)
    return emit_project(ir_project)


def run_authored_project(
    source: str | Path | ModuleType,
    *,
    project_attr: str = "project",
    seconds: float = 1.0,
    dt: float = 1 / 30,
) -> tuple[Project, Sb3Vm]:
    project = build_project(source, project_attr=project_attr)
    vm = Sb3Vm(project)
    vm.run_for(seconds, dt=dt)
    return project, vm


@dataclass
class CompileContext:
    module_globals: dict[str, Any]
    target: TargetBuilder
    procedures: dict[str, ProcedureBinding]
    project: ScratchProject
    parameters: tuple[str, ...] = ()


def lower_authoring_project(authoring: ScratchProject) -> CgProject:
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
            if binding.trigger_value:
                broadcasts.add(binding.trigger_value)
        for name, binding in proc_bindings.items():
            fn_node = get_function_ast(binding.function)
            argument_names = tuple(arg.arg for arg in fn_node.args.args)
            body = lower_function(binding.function, target, authoring, parameters=argument_names, procedures=proc_bindings)
            procedures.append(
                CgProcedure(
                    target_name=target.name,
                    name=name,
                    proccode=_procedure_proccode(name, argument_names),
                    argument_ids=tuple(f"arg:{name}:{index}" for index, _ in enumerate(argument_names)),
                    argument_names=argument_names,
                    argument_defaults=tuple("" for _ in argument_names),
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
                visible=target.visible,
                current_costume=target.current_costume,
            )
        )
    return CgProject(name=authoring.name, targets=tuple(targets), broadcasts=tuple(sorted(broadcasts)))


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
) -> list[CgStmt]:
    fn_node = get_function_ast(fn)
    context = CompileContext(
        module_globals=fn.__globals__,
        target=target,
        project=project,
        procedures=procedures,
        parameters=parameters,
    )
    return [stmt for node in fn_node.body for stmt in lower_stmt(node, context)]


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
    if name == "set_x" and len(args) == 1:
        return CgStmt("move_state", {"mode": "set_x", "x": args[0]})
    if name == "set_y" and len(args) == 1:
        return CgStmt("move_state", {"mode": "set_y", "y": args[0]})
    if name == "change_x_by" and len(args) == 1:
        return CgStmt("move_state", {"mode": "change_x", "dx": args[0]})
    if name == "change_y_by" and len(args) == 1:
        return CgStmt("move_state", {"mode": "change_y", "dy": args[0]})
    if name == "hide" and not args:
        return CgStmt("looks_state", {"mode": "hide"})
    if name == "show" and not args:
        return CgStmt("looks_state", {"mode": "show"})
    if name in context.procedures:
        proc = context.procedures[name]
        if proc.target_name != context.target.name:
            raise CodegenError("Procedures can only be called within the same target in v1")
        fn_node = get_function_ast(proc.function)
        if len(node.args) != len(fn_node.args.args):
            raise CodegenError(f"Procedure {name} argument count mismatch")
        arg_ids = {f"arg:{name}:{index}": lower_expr(arg, context) for index, arg in enumerate(node.args)}
        return CgStmt("proc_call", {"proccode": _procedure_proccode(name, tuple(arg.arg for arg in fn_node.args.args)), "arguments": arg_ids})
    raise CodegenError(f"Unsupported call in statement position: {name}")


def lower_expr(node: ast.AST, context: CompileContext) -> CgExpr:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return CgExpr("literal", "true" if node.value else "false")
        return CgExpr("literal", node.value)
    if isinstance(node, ast.Name):
        if node.id in context.parameters:
            return CgExpr("proc_arg", node.id)
        handle = context.module_globals.get(node.id)
        if isinstance(handle, VariableHandle):
            return CgExpr("var", handle.name)
        if isinstance(handle, ListHandle):
            raise CodegenError("Lists cannot be used directly as expressions; use explicit list intrinsics/reporters")
        raise CodegenError(f"Unknown name in authoring expression: {node.id}")
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
        if not isinstance(node.func, ast.Name):
            raise CodegenError("Only direct function calls are supported in expressions")
        name = node.func.id
        args = tuple(lower_expr(arg, context) for arg in node.args)
        if name == "timer" and not args:
            return CgExpr("timer")
        if name == "answer" and not args:
            return CgExpr("answer")
        if name == "mouse_x" and not args:
            return CgExpr("mouse_x")
        if name == "mouse_y" and not args:
            return CgExpr("mouse_y")
        if name == "mouse_down" and not args:
            return CgExpr("mouse_down")
        if name == "key_pressed" and len(args) == 1:
            return CgExpr("key_pressed", args=args)
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
    expr = lower_expr(node, context)
    if expr.kind != "literal" or not isinstance(expr.value, str):
        raise CodegenError("This intrinsic requires a literal string argument in v1")
    return expr.value


def _procedure_proccode(name: str, arguments: tuple[str, ...]) -> str:
    return " ".join([name, *(["%s"] * len(arguments))]).strip()


class _BlockEmitter:
    def __init__(self, target: CgTarget, *, broadcasts: dict[str, str], variable_ids: dict[tuple[str, str], str], list_ids: dict[tuple[str, str], str]) -> None:
        self.target = target
        self.broadcasts = broadcasts
        self.variable_ids = variable_ids
        self.list_ids = list_ids
        self.blocks: dict[str, dict[str, Any]] = {}
        self.counter = 0

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
        self.blocks[hat_id] = {
            "opcode": "event_whenflagclicked" if script.trigger_kind == "green_flag" else "event_whenbroadcastreceived",
            "next": None,
            "parent": None,
            "inputs": {},
            "fields": {"BROADCAST_OPTION": [script.trigger_value, self.broadcasts[script.trigger_value]]} if script.trigger_kind == "broadcast_received" else {},
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
            payload["fields"]["VARIABLE"] = [stmt.args["name"], self.variable_ids[(self.target.name, stmt.args["name"])]]
        elif stmt.kind == "change_var":
            payload["opcode"] = "data_changevariableby"
            payload["inputs"]["VALUE"] = self._expr_input(stmt.args["value"], parent=block_id, procedure=procedure)
            payload["fields"]["VARIABLE"] = [stmt.args["name"], self.variable_ids[(self.target.name, stmt.args["name"])]]
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
        elif stmt.kind == "list_add":
            payload["opcode"] = "data_addtolist"
            payload["inputs"]["ITEM"] = self._expr_input(stmt.args["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self.list_ids[(self.target.name, stmt.args["name"])]]
        elif stmt.kind == "list_delete":
            payload["opcode"] = "data_deleteoflist"
            payload["inputs"]["INDEX"] = self._expr_input(stmt.args["index"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self.list_ids[(self.target.name, stmt.args["name"])]]
        elif stmt.kind == "list_delete_all":
            payload["opcode"] = "data_deletealloflist"
            payload["fields"]["LIST"] = [stmt.args["name"], self.list_ids[(self.target.name, stmt.args["name"])]]
        elif stmt.kind == "list_insert":
            payload["opcode"] = "data_insertatlist"
            payload["inputs"]["INDEX"] = self._expr_input(stmt.args["index"], parent=block_id, procedure=procedure)
            payload["inputs"]["ITEM"] = self._expr_input(stmt.args["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self.list_ids[(self.target.name, stmt.args["name"])]]
        elif stmt.kind == "list_replace":
            payload["opcode"] = "data_replaceitemoflist"
            payload["inputs"]["INDEX"] = self._expr_input(stmt.args["index"], parent=block_id, procedure=procedure)
            payload["inputs"]["ITEM"] = self._expr_input(stmt.args["item"], parent=block_id, procedure=procedure)
            payload["fields"]["LIST"] = [stmt.args["name"], self.list_ids[(self.target.name, stmt.args["name"])]]
        elif stmt.kind == "move_state":
            mode = stmt.args["mode"]
            if mode == "goto_xy":
                payload["opcode"] = "motion_gotoxy"
                payload["inputs"]["X"] = self._expr_input(stmt.args["x"], parent=block_id, procedure=procedure)
                payload["inputs"]["Y"] = self._expr_input(stmt.args["y"], parent=block_id, procedure=procedure)
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
            else:
                raise CodegenError(f"Unsupported movement mode {mode!r}")
        elif stmt.kind == "looks_state":
            mode = stmt.args["mode"]
            if mode == "hide":
                payload["opcode"] = "looks_hide"
            elif mode == "show":
                payload["opcode"] = "looks_show"
            else:
                raise CodegenError(f"Unsupported looks mode {mode!r}")
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
            payload["fields"]["VARIABLE"] = [expr.value, self.variable_ids[(self.target.name, expr.value)]]
        elif expr.kind == "proc_arg":
            if procedure is None:
                raise CodegenError("Procedure arguments can only be used inside procedures")
            payload["opcode"] = "argument_reporter_string_number"
            payload["fields"]["VALUE"] = [expr.value, None]
        elif expr.kind in {"operator_add", "operator_subtract", "operator_multiply", "operator_divide", "operator_mod", "operator_equals", "operator_lt", "operator_gt"}:
            opcode_map = {
                "operator_add": "operator_add",
                "operator_subtract": "operator_subtract",
                "operator_multiply": "operator_multiply",
                "operator_divide": "operator_divide",
                "operator_mod": "operator_mod",
                "operator_equals": "operator_equals",
                "operator_lt": "operator_lt",
                "operator_gt": "operator_gt",
            }
            payload["opcode"] = opcode_map[expr.kind]
            payload["inputs"]["NUM1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["NUM2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind in {"operator_and", "operator_or"}:
            payload["opcode"] = expr.kind
            payload["inputs"]["OPERAND1"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
            payload["inputs"]["OPERAND2"] = self._expr_input(expr.args[1], parent=block_id, procedure=procedure)
        elif expr.kind == "operator_not":
            payload["opcode"] = "operator_not"
            payload["inputs"]["OPERAND"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
        elif expr.kind == "timer":
            payload["opcode"] = "sensing_timer"
        elif expr.kind == "answer":
            payload["opcode"] = "sensing_answer"
        elif expr.kind == "mouse_x":
            payload["opcode"] = "sensing_mousex"
        elif expr.kind == "mouse_y":
            payload["opcode"] = "sensing_mousey"
        elif expr.kind == "mouse_down":
            payload["opcode"] = "sensing_mousedown"
        elif expr.kind == "key_pressed":
            payload["opcode"] = "sensing_keypressed"
            payload["inputs"]["KEY_OPTION"] = self._expr_input(expr.args[0], parent=block_id, procedure=procedure)
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
        }
        if not target.is_stage:
            target_json.update(
                {
                    "x": target.x,
                    "y": target.y,
                    "visible": target.visible,
                    "currentCostume": target.current_costume,
                }
            )
        targets_json.append(target_json)

    return Project.from_json(
        {
            "targets": targets_json,
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0", "vm": project.name},
        }
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
