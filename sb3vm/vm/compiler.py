from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generator

from sb3vm.parse.ast_nodes import AskState
from sb3vm.vm.input_provider import normalize_key_name
from sb3vm.vm.ir import IrExpr, IrScript, IrStmt
from sb3vm.vm.scratch_values import list_contains, list_contents, resolve_list_index, to_bool, to_number, to_string
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


CompiledRunner = Generator[str | None, None, None]
ExprFn = Callable[[Any, Any], Any]
StmtFn = Callable[[Any, Any], CompiledRunner]


@dataclass(frozen=True)
class CompiledScript:
    key: str
    target_name: str
    generator_factory: Callable[[Any, Any], CompiledRunner]


def compile_script(ir_script: IrScript) -> CompiledScript:
    stmt_fns = tuple(compile_stmt(stmt) for stmt in ir_script.body)

    def run(vm: Any, thread: Any) -> CompiledRunner:
        for stmt_fn in stmt_fns:
            yield from stmt_fn(vm, thread)

    return CompiledScript(
        key=ir_script.key,
        target_name=ir_script.target_name,
        generator_factory=run,
    )


def compile_stmt(stmt: IrStmt) -> StmtFn:
    kind = stmt.kind
    if kind == "set_var":
        name = stmt.get("name")
        value_fn = compile_expr(stmt.get("value"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            vm._set_var(thread.instance_id, name, value_fn(vm, thread))
            yield "yield"

        return run
    if kind == "change_var":
        name = stmt.get("name")
        value_fn = compile_expr(stmt.get("value"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            cur = vm._get_var(thread.instance_id, name)
            vm._set_var(thread.instance_id, name, to_number(cur) + to_number(value_fn(vm, thread)))
            yield "yield"

        return run
    if kind == "list_add":
        name = stmt.get("name")
        item_fn = compile_expr(stmt.get("item"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            vm._get_list(thread.instance_id, name).append(item_fn(vm, thread))
            yield "yield"

        return run
    if kind == "list_delete":
        name = stmt.get("name")
        index_fn = compile_expr(stmt.get("index"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            lst = vm._get_list(thread.instance_id, name)
            idx = resolve_list_index(index_fn(vm, thread), len(lst), random_index=vm.random_index)
            if idx is not None:
                del lst[idx]
            yield "yield"

        return run
    if kind == "list_delete_all":
        name = stmt.get("name")

        def run(vm: Any, thread: Any) -> CompiledRunner:
            vm._get_list(thread.instance_id, name).clear()
            yield "yield"

        return run
    if kind == "list_insert":
        name = stmt.get("name")
        index_fn = compile_expr(stmt.get("index"))
        item_fn = compile_expr(stmt.get("item"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            lst = vm._get_list(thread.instance_id, name)
            idx = vm._resolve_insert_index_value(index_fn(vm, thread), len(lst))
            lst.insert(idx, item_fn(vm, thread))
            yield "yield"

        return run
    if kind == "list_replace":
        name = stmt.get("name")
        index_fn = compile_expr(stmt.get("index"))
        item_fn = compile_expr(stmt.get("item"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            lst = vm._get_list(thread.instance_id, name)
            idx = resolve_list_index(index_fn(vm, thread), len(lst), random_index=vm.random_index)
            if idx is not None:
                lst[idx] = item_fn(vm, thread)
            yield "yield"

        return run
    if kind == "wait":
        duration_fn = compile_expr(stmt.get("duration"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            thread.wake_time = vm.state.time_seconds + max(0.0, to_number(duration_fn(vm, thread)))
            yield "block"

        return run
    if kind == "music_play_note":
        note_fn = compile_expr(stmt.get("note"))
        beats_fn = compile_expr(stmt.get("beats"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            note_fn(vm, thread)
            thread.wake_time = vm.state.time_seconds + vm._beats_to_seconds(beats_fn(vm, thread))
            yield "block"

        return run
    if kind == "repeat":
        times_fn = compile_expr(stmt.get("times"))
        body_fns = tuple(compile_stmt(item) for item in stmt.get("body"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            for _ in range(max(0, int(to_number(times_fn(vm, thread))))):
                for body_fn in body_fns:
                    yield from body_fn(vm, thread)

        return run
    if kind == "forever":
        body_fns = tuple(compile_stmt(item) for item in stmt.get("body"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            while True:
                for body_fn in body_fns:
                    yield from body_fn(vm, thread)
                yield "yield"

        return run
    if kind == "if":
        condition_fn = compile_expr(stmt.get("condition"))
        body_fns = tuple(compile_stmt(item) for item in stmt.get("body"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            if to_bool(condition_fn(vm, thread)):
                for body_fn in body_fns:
                    yield from body_fn(vm, thread)

        return run
    if kind == "if_else":
        condition_fn = compile_expr(stmt.get("condition"))
        body_fns = tuple(compile_stmt(item) for item in stmt.get("body"))
        else_fns = tuple(compile_stmt(item) for item in stmt.get("else_body"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            branch = body_fns if to_bool(condition_fn(vm, thread)) else else_fns
            for body_fn in branch:
                yield from body_fn(vm, thread)

        return run
    if kind == "repeat_until":
        condition_fn = compile_expr(stmt.get("condition"))
        body_fns = tuple(compile_stmt(item) for item in stmt.get("body"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            while not to_bool(condition_fn(vm, thread)):
                for body_fn in body_fns:
                    yield from body_fn(vm, thread)
                yield "yield"

        return run
    if kind == "broadcast":
        name_value = stmt.get("name")
        name_fn = compile_expr(name_value) if isinstance(name_value, IrExpr) else (lambda vm, thread: name_value)
        wait = bool(stmt.get("wait"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            child_ids = vm.emit_broadcast(str(name_fn(vm, thread)), wait_parent=thread if wait else None)
            if wait and child_ids:
                yield "block"
            else:
                yield "yield"

        return run
    if kind == "ask":
        prompt_fn = compile_expr(stmt.get("prompt"))

        def run(vm: Any, thread: Any) -> CompiledRunner:
            prompt = to_string(prompt_fn(vm, thread))
            answer = vm.input_provider.pop_answer()
            if answer is None:
                thread.waiting_for_answer = AskState(prompt=prompt)
                yield "block"
                return
            vm.input_provider.set_answer(answer)
            yield "yield"

        return run
    if kind == "stop":
        mode = str(stmt.get("mode")).lower()

        def run(vm: Any, thread: Any) -> CompiledRunner:
            result = vm._handle_stop(thread, mode)
            if result is not None:
                yield result

        return run
    if kind == "move_state":
        mode = stmt.get("mode")
        compiled_args = {name: compile_expr(value) for name, value in stmt.args if isinstance(value, IrExpr)}
        raw_args = {name: value for name, value in stmt.args if not isinstance(value, IrExpr)}

        def run(vm: Any, thread: Any) -> CompiledRunner:
            values = {name: expr_fn(vm, thread) for name, expr_fn in compiled_args.items()}
            result = vm._execute_move_state(thread, mode, {**raw_args, **values})
            if result == "block":
                yield "block"
            else:
                yield "yield"

        return run
    if kind == "looks_state":
        mode = stmt.get("mode")
        compiled_args = {name: compile_expr(value) for name, value in stmt.args if isinstance(value, IrExpr)}
        raw_args = {name: value for name, value in stmt.args if not isinstance(value, IrExpr)}

        def run(vm: Any, thread: Any) -> CompiledRunner:
            values = {name: expr_fn(vm, thread) for name, expr_fn in compiled_args.items()}
            result = vm._execute_looks_state(thread, mode, {**raw_args, **values})
            if result == "block":
                yield "block"
            else:
                yield "yield"

        return run
    if kind == "reset_timer":
        def run(vm: Any, thread: Any) -> CompiledRunner:
            vm.state.reset_timer()
            yield "yield"

        return run
    raise ValueError(f"Unsupported compiled statement: {kind}")


def compile_expr(expr: IrExpr) -> ExprFn:
    kind = expr.kind
    if kind == "literal":
        return lambda vm, thread: expr.value
    if kind == "timer":
        return lambda vm, thread: vm.timer_seconds()
    if kind == "answer":
        return lambda vm, thread: vm.input_provider.current_answer()
    if kind == "key_pressed":
        arg_fns = tuple(compile_expr(arg) for arg in expr.args)
        return lambda vm, thread: vm.input_provider.key_pressed(normalize_key_name(str(arg_fns[0](vm, thread))))
    if kind == "mouse_x":
        return lambda vm, thread: vm.input_provider.mouse_x()
    if kind == "mouse_y":
        return lambda vm, thread: vm.input_provider.mouse_y()
    if kind == "mouse_down":
        return lambda vm, thread: vm.input_provider.mouse_down()
    if kind == "touching_object":
        arg_fns = tuple(compile_expr(arg) for arg in expr.args)
        return lambda vm, thread: vm.touching_object(thread.instance_id, arg_fns[0](vm, thread))
    if kind == "x_position":
        return lambda vm, thread: vm.state.instances[thread.instance_id].x
    if kind == "y_position":
        return lambda vm, thread: vm.state.instances[thread.instance_id].y
    if kind == "direction":
        return lambda vm, thread: vm.state.instances[thread.instance_id].direction
    if kind == "size":
        return lambda vm, thread: vm.state.instances[thread.instance_id].size
    if kind == "var":
        name = expr.value
        return lambda vm, thread: vm._get_var(thread.instance_id, name)
    if kind == "list_item":
        info = expr.value
        index_fn = compile_expr(info["index"])

        def run(vm: Any, thread: Any) -> Any:
            lst = vm._get_list(thread.instance_id, info["name"])
            idx = resolve_list_index(index_fn(vm, thread), len(lst), random_index=vm.random_index)
            return "" if idx is None else lst[idx]

        return run
    if kind == "list_length":
        name = expr.value
        return lambda vm, thread: len(vm._get_list(thread.instance_id, name))
    if kind == "list_contains":
        info = expr.value
        item_fn = compile_expr(info["item"])
        return lambda vm, thread: list_contains(vm._get_list(thread.instance_id, info["name"]), item_fn(vm, thread))
    if kind == "list_contents":
        name = expr.value
        return lambda vm, thread: list_contents(vm._get_list(thread.instance_id, name))
    if kind == "costume_info":
        selector = str(expr.value).lower()

        def run(vm: Any, thread: Any) -> Any:
            instance = vm.state.instances[thread.instance_id]
            costumes = vm.project.get_target(instance.source_target_name).costumes
            if not costumes:
                return 0 if selector == "number" else ""
            costume = costumes[instance.costume_index % len(costumes)]
            return instance.costume_index + 1 if selector == "number" else costume.get("name", "")

        return run
    if kind == "backdrop_info":
        selector = str(expr.value).lower()

        def run(vm: Any, thread: Any) -> Any:
            stage = vm.state.targets["Stage"]
            costumes = vm.project.get_target(stage.source_target_name).costumes
            if not costumes:
                return 0 if selector == "number" else ""
            costume = costumes[stage.costume_index % len(costumes)]
            return stage.costume_index + 1 if selector == "number" else costume.get("name", "")

        return run

    arg_fns = tuple(compile_expr(arg) for arg in expr.args)
    if kind == "operator_add":
        return lambda vm, thread: to_number(arg_fns[0](vm, thread)) + to_number(arg_fns[1](vm, thread))
    if kind == "operator_subtract":
        return lambda vm, thread: to_number(arg_fns[0](vm, thread)) - to_number(arg_fns[1](vm, thread))
    if kind == "operator_multiply":
        return lambda vm, thread: to_number(arg_fns[0](vm, thread)) * to_number(arg_fns[1](vm, thread))
    if kind == "operator_divide":
        def run(vm: Any, thread: Any) -> Any:
            rhs = to_number(arg_fns[1](vm, thread))
            return to_number(arg_fns[0](vm, thread)) / rhs if rhs != 0 else float("inf")
        return run
    if kind == "operator_mod":
        def run(vm: Any, thread: Any) -> Any:
            rhs = to_number(arg_fns[1](vm, thread))
            return to_number(arg_fns[0](vm, thread)) % rhs if rhs != 0 else float("nan")
        return run
    if kind == "operator_random":
        def run(vm: Any, thread: Any) -> Any:
            a = to_number(arg_fns[0](vm, thread))
            b = to_number(arg_fns[1](vm, thread))
            lo, hi = sorted((a, b))
            if lo.is_integer() and hi.is_integer():
                return vm.rng.randint(int(lo), int(hi))
            return vm.rng.uniform(lo, hi)
        return run
    if kind == "operator_equals":
        return lambda vm, thread: vm._compare_equal(arg_fns[0](vm, thread), arg_fns[1](vm, thread))
    if kind == "operator_lt":
        return lambda vm, thread: vm._compare_order(arg_fns[0](vm, thread), arg_fns[1](vm, thread), "<")
    if kind == "operator_gt":
        return lambda vm, thread: vm._compare_order(arg_fns[0](vm, thread), arg_fns[1](vm, thread), ">")
    if kind == "operator_and":
        return lambda vm, thread: to_bool(arg_fns[0](vm, thread)) and to_bool(arg_fns[1](vm, thread))
    if kind == "operator_or":
        return lambda vm, thread: to_bool(arg_fns[0](vm, thread)) or to_bool(arg_fns[1](vm, thread))
    if kind == "operator_not":
        return lambda vm, thread: not to_bool(arg_fns[0](vm, thread))
    if kind == "operator_join":
        return lambda vm, thread: f"{to_string(arg_fns[0](vm, thread))}{to_string(arg_fns[1](vm, thread))}"
    if kind == "operator_letter_of":
        return lambda vm, thread: vm._letter_of(arg_fns[0](vm, thread), arg_fns[1](vm, thread))
    if kind == "operator_length":
        return lambda vm, thread: len(to_string(arg_fns[0](vm, thread)))
    if kind == "operator_contains":
        return lambda vm, thread: to_string(arg_fns[1](vm, thread)).lower() in to_string(arg_fns[0](vm, thread)).lower()
    if kind == "operator_round":
        return lambda vm, thread: round(to_number(arg_fns[0](vm, thread)))
    if kind == "operator_mathop":
        op = str(expr.value).lower()

        def run(vm: Any, thread: Any) -> Any:
            return vm._apply_mathop(op, to_number(arg_fns[0](vm, thread)))

        return run
    raise ValueError(f"Unsupported compiled expression: {kind}")

