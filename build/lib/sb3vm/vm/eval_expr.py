from __future__ import annotations

import math
from typing import Any

from sb3vm.parse.ast_nodes import Expr
from sb3vm.vm.input_provider import normalize_key_name
from sb3vm.vm.scratch_values import (
    compare_equal,
    compare_order,
    letter_of,
    list_contains,
    list_contents,
    resolve_list_index,
    to_bool,
    to_number,
    to_string,
)
from sb3vm.vm.state import ThreadState, VMState


def eval_expr(expr: Expr, vm_state: VMState, thread: ThreadState, vm: Any) -> Any:
    target = vm_state.instances[thread.instance_id]
    kind = expr.kind
    if kind == "literal":
        return expr.value
    if kind == "proc_arg":
        return thread.current_arguments().get(str(expr.value), 0)
    if kind == "timer":
        return vm.timer_seconds()
    if kind == "answer":
        return vm.input_provider.current_answer()
    if kind == "key_pressed":
        key_name = normalize_key_name(str(eval_expr(expr.args[0], vm_state, thread, vm)))
        return vm.input_provider.key_pressed(key_name)
    if kind == "mouse_x":
        return vm.input_provider.mouse_x()
    if kind == "mouse_y":
        return vm.input_provider.mouse_y()
    if kind == "mouse_down":
        return vm.input_provider.mouse_down()
    if kind == "x_position":
        return target.x
    if kind == "y_position":
        return target.y
    if kind == "direction":
        return target.direction
    if kind == "size":
        return target.size
    if kind == "costume_info":
        costumes = vm.project.get_target(target.source_target_name).costumes
        if not costumes:
            return 0 if str(expr.value).lower() == "number" else ""
        costume = costumes[target.costume_index % len(costumes)]
        return target.costume_index + 1 if str(expr.value).lower() == "number" else costume.get("name", "")
    if kind == "backdrop_info":
        stage = vm_state.targets["Stage"]
        costumes = vm.project.get_target(stage.source_target_name).costumes
        if not costumes:
            return 0 if str(expr.value).lower() == "number" else ""
        costume = costumes[stage.costume_index % len(costumes)]
        return stage.costume_index + 1 if str(expr.value).lower() == "number" else costume.get("name", "")
    if kind == "var":
        return target.local_variables.get(expr.value, vm_state.stage_variables.get(expr.value, 0))
    if kind == "list_item":
        info = expr.value
        lst = target.local_lists.get(info["name"], vm_state.stage_lists.get(info["name"], []))
        idx = resolve_list_index(eval_expr(info["index"], vm_state, thread, vm), len(lst), random_index=vm.random_index)
        return "" if idx is None else lst[idx]
    if kind == "list_length":
        lst = target.local_lists.get(expr.value, vm_state.stage_lists.get(expr.value, []))
        return len(lst)
    if kind == "list_contains":
        info = expr.value
        lst = target.local_lists.get(info["name"], vm_state.stage_lists.get(info["name"], []))
        return list_contains(lst, eval_expr(info["item"], vm_state, thread, vm))
    if kind == "list_contents":
        lst = target.local_lists.get(expr.value, vm_state.stage_lists.get(expr.value, []))
        return list_contents(lst)

    args = [eval_expr(arg, vm_state, thread, vm) for arg in expr.args]
    if kind == "operator_add":
        return to_number(args[0]) + to_number(args[1])
    if kind == "operator_subtract":
        return to_number(args[0]) - to_number(args[1])
    if kind == "operator_multiply":
        return to_number(args[0]) * to_number(args[1])
    if kind == "operator_divide":
        rhs = to_number(args[1])
        return to_number(args[0]) / rhs if rhs != 0 else math.inf
    if kind == "operator_mod":
        rhs = to_number(args[1])
        return to_number(args[0]) % rhs if rhs != 0 else math.nan
    if kind == "operator_random":
        a = to_number(args[0])
        b = to_number(args[1])
        lo, hi = sorted((a, b))
        if lo.is_integer() and hi.is_integer():
            return vm.rng.randint(int(lo), int(hi))
        return vm.rng.uniform(lo, hi)
    if kind == "operator_equals":
        return compare_equal(args[0], args[1])
    if kind == "operator_lt":
        left, right = compare_order(args[0], args[1])
        return left < right
    if kind == "operator_gt":
        left, right = compare_order(args[0], args[1])
        return left > right
    if kind == "operator_and":
        return to_bool(args[0]) and to_bool(args[1])
    if kind == "operator_or":
        return to_bool(args[0]) or to_bool(args[1])
    if kind == "operator_not":
        return not to_bool(args[0])
    if kind == "operator_join":
        return f"{to_string(args[0])}{to_string(args[1])}"
    if kind == "operator_letter_of":
        return letter_of(args[0], args[1])
    if kind == "operator_length":
        return len(to_string(args[0]))
    if kind == "operator_contains":
        return to_string(args[1]).lower() in to_string(args[0]).lower()
    if kind == "operator_round":
        return round(to_number(args[0]))
    if kind == "operator_mathop":
        value = to_number(args[0])
        op = str(expr.value).lower()
        if op == "abs":
            return abs(value)
        if op == "floor":
            return math.floor(value)
        if op == "ceiling":
            return math.ceil(value)
        if op == "sqrt":
            return math.sqrt(value)
        if op == "sin":
            return math.sin(math.radians(value))
        if op == "cos":
            return math.cos(math.radians(value))
        if op == "tan":
            return math.tan(math.radians(value))
        if op == "asin":
            return math.degrees(math.asin(value))
        if op == "acos":
            return math.degrees(math.acos(value))
        if op == "atan":
            return math.degrees(math.atan(value))
        if op == "ln":
            return math.log(value)
        if op == "log":
            return math.log10(value)
        if op == "e ^":
            return math.exp(value)
        if op == "10 ^":
            return 10 ** value
    raise ValueError(f"Unsupported expression kind: {kind}")
