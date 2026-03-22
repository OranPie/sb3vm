from __future__ import annotations

from typing import Any

from sb3vm.model.project import Project, Target, project_display_name
from sb3vm.parse.ast_nodes import Expr, ProcedureDefinition, Script, Stmt, Trigger
from sb3vm.parse.extract_scripts import extract_scripts
from sb3vm.log import get_logger


_LOGGER = get_logger(__name__)

_BINARY_OPS = {
    "operator_add": "+",
    "operator_subtract": "-",
    "operator_multiply": "*",
    "operator_divide": "/",
    "operator_mod": "%",
    "operator_equals": "==",
    "operator_lt": "<",
    "operator_gt": ">",
}


def format_trigger(trigger: Trigger) -> str:
    if trigger.kind == "green_flag":
        return "when green flag clicked"
    if trigger.kind == "key_pressed":
        return f"when key pressed {trigger.value!r}"
    if trigger.kind == "backdrop_switched":
        return f"when backdrop switched to {trigger.value!r}"
    if trigger.kind == "broadcast_received":
        return f"when broadcast received {trigger.value!r}"
    if trigger.kind == "sprite_clicked":
        return "when this sprite clicked"
    if trigger.kind == "clone_start":
        return "when started as clone"
    return f"when {trigger.kind}"


def format_expr(expr: Expr) -> str:
    kind = expr.kind
    if kind == "literal":
        return repr(expr.value)
    if kind in {"var", "proc_arg"}:
        return str(expr.value)
    if kind == "list_item":
        return f"list_item({expr.value['name']}, {format_expr(expr.value['index'])})"
    if kind == "list_length":
        return f"list_length({expr.value})"
    if kind == "list_contains":
        return f"list_contains({expr.value['name']}, {format_expr(expr.value['item'])})"
    if kind == "list_contents":
        return f"list_contents({expr.value})"
    if kind in _BINARY_OPS:
        return f"({format_expr(expr.args[0])} {_BINARY_OPS[kind]} {format_expr(expr.args[1])})"
    if kind == "operator_and":
        return f"({format_expr(expr.args[0])} and {format_expr(expr.args[1])})"
    if kind == "operator_or":
        return f"({format_expr(expr.args[0])} or {format_expr(expr.args[1])})"
    if kind == "operator_not":
        return f"(not {format_expr(expr.args[0])})"
    if kind == "operator_join":
        return f"join({format_expr(expr.args[0])}, {format_expr(expr.args[1])})"
    if kind == "operator_letter_of":
        return f"letter_of({format_expr(expr.args[0])}, {format_expr(expr.args[1])})"
    if kind == "operator_length":
        return f"string_length({format_expr(expr.args[0])})"
    if kind == "operator_contains":
        return f"string_contains({format_expr(expr.args[0])}, {format_expr(expr.args[1])})"
    if kind == "operator_round":
        return f"round_value({format_expr(expr.args[0])})"
    if kind == "operator_mathop":
        return f"math_op({expr.value!r}, {format_expr(expr.args[0])})"
    if kind == "operator_random":
        return f"random_between({format_expr(expr.args[0])}, {format_expr(expr.args[1])})"
    if kind == "timer":
        return "timer()"
    if kind == "answer":
        return "answer()"
    if kind == "key_pressed":
        return f"key_pressed({format_expr(expr.args[0])})"
    if kind == "mouse_x":
        return "mouse_x()"
    if kind == "mouse_y":
        return "mouse_y()"
    if kind == "mouse_down":
        return "mouse_down()"
    if kind == "touching_object":
        return f"touching_object({format_expr(expr.args[0])})"
    if kind == "x_position":
        return "x_position()"
    if kind == "y_position":
        return "y_position()"
    if kind == "direction":
        return "direction()"
    if kind == "size":
        return "size()"
    if kind == "costume_info":
        return "costume_name()" if str(expr.value) == "name" else "costume_number()"
    if kind == "backdrop_info":
        return "backdrop_name()" if str(expr.value) == "name" else "backdrop_number()"
    if kind == "unsupported":
        return f"unsupported({expr.value!r})"
    return f"{kind}({', '.join(format_expr(arg) for arg in expr.args)})"


def summarize_stmt(stmt: Stmt) -> str:
    kind = stmt.kind
    if kind == "set_var":
        return f"{stmt.args['name']} = {format_expr(stmt.args['value'])}"
    if kind == "change_var":
        return f"{stmt.args['name']} += {format_expr(stmt.args['value'])}"
    if kind == "list_add":
        return f"add_to_list({stmt.args['name']}, {format_expr(stmt.args['item'])})"
    if kind == "list_delete":
        return f"delete_from_list({stmt.args['name']}, {format_expr(stmt.args['index'])})"
    if kind == "list_delete_all":
        return f"delete_all_of_list({stmt.args['name']})"
    if kind == "list_insert":
        return f"insert_at_list({stmt.args['name']}, {format_expr(stmt.args['index'])}, {format_expr(stmt.args['item'])})"
    if kind == "list_replace":
        return f"replace_in_list({stmt.args['name']}, {format_expr(stmt.args['index'])}, {format_expr(stmt.args['item'])})"
    if kind == "wait":
        return f"wait({format_expr(stmt.args['duration'])})"
    if kind == "repeat":
        return f"repeat {format_expr(stmt.args['times'])}"
    if kind == "forever":
        return "forever"
    if kind == "if":
        return f"if {format_expr(stmt.args['condition'])}"
    if kind == "if_else":
        return f"if {format_expr(stmt.args['condition'])} else"
    if kind == "repeat_until":
        return f"repeat until {format_expr(stmt.args['condition'])}"
    if kind == "broadcast":
        fn = "broadcast_wait" if stmt.args['wait'] else "broadcast"
        return f"{fn}({stmt.args['name']!r})"
    if kind == "stop":
        return f"stop({stmt.args['mode']!r})"
    if kind == "move_state":
        mode = stmt.args['mode']
        if mode == 'goto_xy':
            return f"goto_xy({format_expr(stmt.args['x'])}, {format_expr(stmt.args['y'])})"
        if mode == 'goto_target':
            return f"goto_target({format_expr(stmt.args['target'])})"
        if mode == 'glide_xy':
            return f"glide_xy({format_expr(stmt.args['duration'])}, {format_expr(stmt.args['x'])}, {format_expr(stmt.args['y'])})"
        if mode == 'glide_target':
            return f"glide_to({format_expr(stmt.args['duration'])}, {format_expr(stmt.args['target'])})"
        if mode == 'set_x':
            return f"set_x({format_expr(stmt.args['x'])})"
        if mode == 'set_y':
            return f"set_y({format_expr(stmt.args['y'])})"
        if mode == 'change_x':
            return f"change_x_by({format_expr(stmt.args['dx'])})"
        if mode == 'change_y':
            return f"change_y_by({format_expr(stmt.args['dy'])})"
        if mode == 'turn_right':
            return f"turn_right({format_expr(stmt.args['degrees'])})"
        if mode == 'turn_left':
            return f"turn_left({format_expr(stmt.args['degrees'])})"
        if mode == 'point_direction':
            return f"point_in_direction({format_expr(stmt.args['direction'])})"
        if mode == 'point_towards':
            return f"point_towards({format_expr(stmt.args['target'])})"
        if mode == 'set_rotation_style':
            return f"set_rotation_style({stmt.args['style']!r})"
        return f"move_state({mode})"
    if kind == "looks_state":
        mode = stmt.args['mode']
        if mode == 'show':
            return 'show()'
        if mode == 'hide':
            return 'hide()'
        if mode == 'dialogue':
            fn = 'say' if stmt.args['style'] == 'say' else 'think'
            if 'duration' in stmt.args:
                fn = 'say_for_secs' if stmt.args['style'] == 'say' else 'think_for_secs'
                return f"{fn}({format_expr(stmt.args['message'])}, {format_expr(stmt.args['duration'])})"
            return f"{fn}({format_expr(stmt.args['message'])})"
        if mode == 'switch_costume':
            return f"switch_costume({format_expr(stmt.args['costume'])})"
        if mode == 'next_costume':
            return 'next_costume()'
        if mode == 'switch_backdrop':
            fn = 'switch_backdrop_wait' if stmt.args['wait'] else 'switch_backdrop'
            return f"{fn}({format_expr(stmt.args['backdrop'])})"
        if mode == 'next_backdrop':
            return 'next_backdrop()'
        if mode == 'set_size':
            return f"set_size({format_expr(stmt.args['size'])})"
        if mode == 'change_size':
            return f"change_size_by({format_expr(stmt.args['delta'])})"
        if mode == 'set_effect':
            return f"set_effect({stmt.args['effect']!r}, {format_expr(stmt.args['value'])})"
        if mode == 'change_effect':
            return f"change_effect_by({stmt.args['effect']!r}, {format_expr(stmt.args['value'])})"
        if mode == 'clear_effects':
            return 'clear_graphic_effects()'
        if mode == 'go_front_back':
            return f"go_front_back({stmt.args['direction']!r})"
        if mode == 'go_layers':
            return f"go_layers({stmt.args['direction']!r}, {format_expr(stmt.args['layers'])})"
        return f"looks_state({mode})"
    if kind == "create_clone":
        return f"create_clone({stmt.args['selector']!r})"
    if kind == "delete_clone":
        return "delete_this_clone()"
    if kind == "ask":
        return f"ask({format_expr(stmt.args['prompt'])})"
    if kind == "reset_timer":
        return "reset_timer()"
    if kind == "music_play_note":
        return f"play_note_for_beats({format_expr(stmt.args['note'])}, {format_expr(stmt.args['beats'])})"
    if kind == "proc_call":
        args = ", ".join(f"{name}={format_expr(value)}" for name, value in stmt.args['arguments'].items())
        return f"{stmt.args['proccode']}({args})"
    if kind == "unsupported":
        return f"unsupported({stmt.args!r})"
    return f"{kind}({stmt.args!r})"


def format_stmt_block(stmt: Stmt, indent: str = "") -> list[str]:
    head = summarize_stmt(stmt)
    if stmt.kind == "repeat":
        lines = [f"{indent}{head}:"]
        lines.extend(_format_body(stmt.args['body'], indent + "    "))
        return lines
    if stmt.kind == "forever":
        lines = [f"{indent}{head}:"]
        lines.extend(_format_body(stmt.args['body'], indent + "    "))
        return lines
    if stmt.kind == "if":
        lines = [f"{indent}{head}:"]
        lines.extend(_format_body(stmt.args['body'], indent + "    "))
        return lines
    if stmt.kind == "if_else":
        lines = [f"{indent}if {format_expr(stmt.args['condition'])}:"]
        lines.extend(_format_body(stmt.args['body'], indent + "    "))
        lines.append(f"{indent}else:")
        lines.extend(_format_body(stmt.args['else_body'], indent + "    "))
        return lines
    if stmt.kind == "repeat_until":
        lines = [f"{indent}{head}:"]
        lines.extend(_format_body(stmt.args['body'], indent + "    "))
        return lines
    return [f"{indent}{head}"]


def _format_body(body: list[Stmt], indent: str) -> list[str]:
    if not body:
        return [f"{indent}pass"]
    lines: list[str] = []
    for stmt in body:
        lines.extend(format_stmt_block(stmt, indent))
    return lines


def _render_target(target: Target, procedures: list[ProcedureDefinition], scripts: list[Script]) -> list[str]:
    kind = "stage" if target.is_stage else "sprite"
    lines = [f"Target: {target.name} [{kind}]"]
    if target.variables:
        lines.append("  Variables:")
        for _, (name, value) in sorted(target.variables.items(), key=lambda item: item[1][0]):
            lines.append(f"    {name} = {value!r}")
    if target.lists:
        lines.append("  Lists:")
        for _, (name, value) in sorted(target.lists.items(), key=lambda item: item[1][0]):
            lines.append(f"    {name} = {list(value)!r}")
    if procedures:
        lines.append("  Procedures:")
        for procedure in procedures:
            suffix = " [warp]" if procedure.warp else ""
            lines.append(f"    {procedure.proccode}{suffix}")
            lines.extend(_format_body(procedure.body, "      "))
    if scripts:
        lines.append("  Scripts:")
        for script in scripts:
            lines.append(f"    {format_trigger(script.trigger)}")
            lines.extend(_format_body(script.body, "      "))
            if not script.supported and script.unsupported_details:
                for detail in script.unsupported_details:
                    lines.append(f"      unsupported: {detail.reason} ({detail.opcode})")
    return lines


def render_project_text(project: Project) -> str:
    parsed = extract_scripts(project)
    lines = [f"Project: {project_display_name(project.meta)}"]
    if project.extensions:
        lines.append("Extensions: " + ", ".join(project.extensions))
    if project.assets:
        lines.append("Assets: " + ", ".join(sorted(project.assets)))
    if project.extensions or project.assets:
        lines.append("")
    procedures_by_target: dict[str, list[ProcedureDefinition]] = {}
    for procedure in parsed.procedures:
        procedures_by_target.setdefault(procedure.target_name, []).append(procedure)
    scripts_by_target: dict[str, list[Script]] = {}
    for script in parsed.scripts:
        scripts_by_target.setdefault(script.target_name, []).append(script)
    for index, target in enumerate(project.targets):
        if index:
            lines.append("")
        lines.extend(_render_target(target, procedures_by_target.get(target.name, []), scripts_by_target.get(target.name, [])))
    return "\n".join(lines) + "\n"
