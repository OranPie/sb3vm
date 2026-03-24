from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sb3vm.parse.ast_nodes import Expr, Script, Stmt
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)


SAFE_EXPR_KINDS = {
    "literal",
    "var",
    "list_item",
    "list_length",
    "list_contains",
    "list_contents",
    "x_position",
    "y_position",
    "direction",
    "size",
    "costume_info",
    "backdrop_info",
    "timer",
    "answer",
    "key_pressed",
    "mouse_x",
    "mouse_y",
    "mouse_down",
    "touching_object",
    "operator_add",
    "operator_subtract",
    "operator_multiply",
    "operator_divide",
    "operator_mod",
    "operator_random",
    "operator_equals",
    "operator_lt",
    "operator_gt",
    "operator_and",
    "operator_or",
    "operator_not",
    "operator_join",
    "operator_letter_of",
    "operator_length",
    "operator_contains",
    "operator_round",
    "operator_mathop",
    # Sensing (added in compatibility pass)
    "sensing_of",
    "distance_to",
    "loudness",
    "current_time",
    "days_since_2000",
    "username",
    "touching_color",
    "color_touching_color",
    "volume",
    # Extension expressions
    "music_tempo",
    "video_sensing",
    "translate",
    "viewer_language",
    # Graceful custom-extension fallback
    "graceful_ext",
}

SAFE_STMT_KINDS = {
    "set_var",
    "change_var",
    "list_add",
    "list_delete",
    "list_delete_all",
    "list_insert",
    "list_replace",
    "wait",
    "no_op",
    "graceful_ext",
    "music_play_note",
    "music_play_drum",
    "music_rest",
    "music_set_instrument",
    "music_set_tempo",
    "music_change_tempo",
    "repeat",
    "forever",
    "if",
    "if_else",
    "repeat_until",
    "broadcast",
    "stop",
    "move_state",
    "looks_state",
    "ask",
    "reset_timer",
}


@dataclass(frozen=True)
class IrExpr:
    kind: str
    value: Any = None
    args: tuple["IrExpr", ...] = ()


@dataclass(frozen=True)
class IrStmt:
    kind: str
    args: tuple[tuple[str, Any], ...] = ()

    def get(self, key: str) -> Any:
        for name, value in self.args:
            if name == key:
                return value
        raise KeyError(key)


@dataclass(frozen=True)
class IrScript:
    key: str
    target_name: str
    trigger_kind: str
    trigger_value: str | None
    supported: bool
    body: tuple[IrStmt, ...]
    compile_safe: bool
    compile_reason: str | None = None


def lower_script(script: Script, key: str) -> IrScript:
    body = tuple(lower_stmt(stmt) for stmt in script.body)
    compile_safe, reason = classify_script(script.supported, body)
    return IrScript(
        key=key,
        target_name=script.target_name,
        trigger_kind=script.trigger.kind,
        trigger_value=script.trigger.value,
        supported=script.supported,
        body=body,
        compile_safe=compile_safe,
        compile_reason=reason,
    )


def lower_stmt(stmt: Stmt) -> IrStmt:
    items: list[tuple[str, Any]] = []
    for key, value in stmt.args.items():
        if isinstance(value, Expr):
            items.append((key, lower_expr(value)))
        elif isinstance(value, list):
            lowered_items = []
            for item in value:
                if isinstance(item, Stmt):
                    lowered_items.append(lower_stmt(item))
                elif isinstance(item, Expr):
                    lowered_items.append(lower_expr(item))
                else:
                    lowered_items.append(item)
            items.append((key, tuple(lowered_items)))
        elif isinstance(value, dict):
            lowered_dict = []
            for name, child in value.items():
                lowered_dict.append((name, lower_expr(child) if isinstance(child, Expr) else child))
            items.append((key, tuple(lowered_dict)))
        else:
            items.append((key, value))
    return IrStmt(kind=stmt.kind, args=tuple(items))


def lower_expr(expr: Expr) -> IrExpr:
    return IrExpr(
        kind=expr.kind,
        value=expr.value,
        args=tuple(lower_expr(arg) for arg in expr.args),
    )


def classify_script(supported: bool, body: tuple[IrStmt, ...]) -> tuple[bool, str | None]:
    if not supported:
        return False, "unsupported_script"
    for stmt in body:
        reason = classify_stmt(stmt)
        if reason is not None:
            return False, reason
    return True, None


def classify_stmt(stmt: IrStmt) -> str | None:
    if stmt.kind not in SAFE_STMT_KINDS:
        return f"stmt:{stmt.kind}"
    for _, value in stmt.args:
        reason = _classify_value(value)
        if reason is not None:
            return reason
    return None


def _classify_value(value: Any) -> str | None:
    if isinstance(value, IrExpr):
        return classify_expr(value)
    if isinstance(value, tuple):
        for item in value:
            reason = _classify_value(item)
            if reason is not None:
                return reason
    return None


def classify_expr(expr: IrExpr) -> str | None:
    if expr.kind not in SAFE_EXPR_KINDS:
        return f"expr:{expr.kind}"
    if isinstance(expr.value, dict):
        for item in expr.value.values():
            if isinstance(item, Expr):
                return "expr:nested_ast"
    for arg in expr.args:
        reason = classify_expr(arg)
        if reason is not None:
            return reason
    return None

