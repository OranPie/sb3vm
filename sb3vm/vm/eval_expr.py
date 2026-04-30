from __future__ import annotations

import datetime
import math
from typing import Any

from sb3vm.log import get_logger
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


_LOGGER = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dispatch table for binary/unary operators (no side effects, args pre-evaled)
# ---------------------------------------------------------------------------

def _op_add(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return to_number(args[0]) + to_number(args[1])

def _op_subtract(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return to_number(args[0]) - to_number(args[1])

def _op_multiply(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return to_number(args[0]) * to_number(args[1])

def _op_divide(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    rhs = to_number(args[1])
    return to_number(args[0]) / rhs if rhs != 0 else math.inf

def _op_mod(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    rhs = to_number(args[1])
    return to_number(args[0]) % rhs if rhs != 0 else math.nan

def _op_random(args: list, expr: Expr, _vs: Any, _t: Any, vm: Any) -> Any:
    a = to_number(args[0])
    b = to_number(args[1])
    lo, hi = sorted((a, b))
    if lo.is_integer() and hi.is_integer():
        return vm.rng.randint(int(lo), int(hi))
    return vm.rng.uniform(lo, hi)

def _op_equals(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return compare_equal(args[0], args[1])

def _op_lt(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    left, right = compare_order(args[0], args[1])
    return left < right

def _op_gt(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    left, right = compare_order(args[0], args[1])
    return left > right

def _op_and(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return to_bool(args[0]) and to_bool(args[1])

def _op_or(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return to_bool(args[0]) or to_bool(args[1])

def _op_not(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return not to_bool(args[0])

def _op_join(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return f"{to_string(args[0])}{to_string(args[1])}"

def _op_letter_of(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return letter_of(args[0], args[1])

def _op_length(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return len(to_string(args[0]))

def _op_contains(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return to_string(args[1]).lower() in to_string(args[0]).lower()

def _op_round(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    return round(to_number(args[0]))

_MATHOP_TABLE: dict[str, Any] = {
    "abs": abs,
    "floor": math.floor,
    "ceiling": math.ceil,
    "sqrt": math.sqrt,
    "ln": math.log,
    "log": math.log10,
    "e ^": math.exp,
}

def _op_mathop(args: list, expr: Expr, _vs: Any, _t: Any, _vm: Any) -> Any:
    value = to_number(args[0])
    op = str(expr.value).lower()
    fn = _MATHOP_TABLE.get(op)
    if fn is not None:
        return fn(value)
    if op == "10 ^":
        return 10 ** value
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
    return 0


_ARGS_DISPATCH: dict[str, Any] = {
    "operator_add": _op_add,
    "operator_subtract": _op_subtract,
    "operator_multiply": _op_multiply,
    "operator_divide": _op_divide,
    "operator_mod": _op_mod,
    "operator_random": _op_random,
    "operator_equals": _op_equals,
    "operator_lt": _op_lt,
    "operator_gt": _op_gt,
    "operator_and": _op_and,
    "operator_or": _op_or,
    "operator_not": _op_not,
    "operator_join": _op_join,
    "operator_letter_of": _op_letter_of,
    "operator_length": _op_length,
    "operator_contains": _op_contains,
    "operator_round": _op_round,
    "operator_mathop": _op_mathop,
}


def _decode_color_arg(raw: Any) -> tuple[int, int, int]:
    """Decode a Scratch color value (int or hex string) to (R,G,B)."""
    if isinstance(raw, str) and raw.strip().startswith("#"):
        h = raw.strip().lstrip("#")
        if len(h) >= 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    try:
        v = int(to_number(raw)) & 0xFFFFFF
        return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
    except (TypeError, ValueError):
        return (0, 0, 0)


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
    if kind == "touching_object":
        return vm.touching_object(thread.instance_id, eval_expr(expr.args[0], vm_state, thread, vm))
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
    if kind == "sensing_of":
        return vm._sensing_of(thread.instance_id, expr.value["property"], eval_expr(expr.value["target"], vm_state, thread, vm))
    if kind == "distance_to":
        return vm._distance_to(thread.instance_id, eval_expr(expr.args[0], vm_state, thread, vm))
    if kind == "loudness":
        return 0
    if kind == "current_time":
        return _eval_current_time(str(expr.value))
    if kind == "days_since_2000":
        return _days_since_2000()
    if kind == "username":
        return ""
    if kind == "touching_color":
        if vm.compositor is None:
            return False
        target_rgb = _decode_color_arg(eval_expr(expr.args[0], vm_state, thread, vm))
        snapshot = vm.render_snapshot()
        return vm.compositor.check_touching_color(snapshot, thread.instance_id, target_rgb)
    if kind == "color_touching_color":
        if vm.compositor is None:
            return False
        sprite_rgb = _decode_color_arg(eval_expr(expr.args[0], vm_state, thread, vm))
        scene_rgb = _decode_color_arg(eval_expr(expr.args[1], vm_state, thread, vm))
        snapshot = vm.render_snapshot()
        return vm.compositor.check_color_touching_color(snapshot, thread.instance_id, sprite_rgb, scene_rgb)
    if kind == "volume":
        return 100

    args = [eval_expr(arg, vm_state, thread, vm) for arg in expr.args]
    handler = _ARGS_DISPATCH.get(kind)
    if handler is not None:
        return handler(args, expr, vm_state, thread, vm)
    if kind == "graceful_ext":
        return ""
    from sb3vm.vm.extensions import eval_ext_expr
    return eval_ext_expr(kind, expr, vm_state, thread, vm)


def _eval_current_time(component: str) -> int:
    now = datetime.datetime.now()
    c = component.upper()
    if c == "YEAR":
        return now.year
    if c == "MONTH":
        return now.month
    if c == "DATE":
        return now.day
    if c == "DAYOFWEEK":
        # Scratch: 1=Sunday … 7=Saturday; Python isoweekday: 1=Monday … 7=Sunday
        return now.isoweekday() % 7 + 1
    if c == "HOUR":
        return now.hour
    if c == "MINUTE":
        return now.minute
    if c == "SECOND":
        return now.second
    return 0


def _days_since_2000() -> float:
    epoch = datetime.datetime(2000, 1, 1)
    delta = datetime.datetime.now() - epoch
    return delta.total_seconds() / 86400.0

