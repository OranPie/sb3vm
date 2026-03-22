from __future__ import annotations

import base64
import keyword
import re
from pathlib import Path
from typing import Any

from sb3vm.io.load_sb3 import load_sb3
from sb3vm.log import debug, get_logger, info, trace
from sb3vm.model.project import Project, Target
from sb3vm.parse.ast_nodes import Expr, ProcedureDefinition, Script, Stmt
from sb3vm.parse.extract_scripts import extract_scripts

from .compiler import CodegenError


_LOGGER = get_logger(__name__)

_IMPORT_NAMES = [
    "EDGE",
    "GraphicEffect",
    "LayerDirection",
    "LayerPosition",
    "MOUSE_POINTER",
    "MYSELF",
    "RANDOM_POSITION",
    "RotationStyle",
    "ScratchProject",
    "StopTarget",
    "answer",
    "join",
    "key_pressed",
    "letter_of",
    "math_op",
    "mouse_down",
    "mouse_x",
    "mouse_y",
    "random_between",
    "round_value",
    "string_contains",
    "string_length",
    "timer",
]

_SPECIAL_SELECTOR_CONSTANTS = {
    "_edge_": "EDGE",
    "_mouse_": "MOUSE_POINTER",
    "_myself_": "MYSELF",
    "_random_": "RANDOM_POSITION",
    "myself": "MYSELF",
}

_EFFECT_ENUMS = {
    "brightness": "GraphicEffect.BRIGHTNESS",
    "color": "GraphicEffect.COLOR",
    "fisheye": "GraphicEffect.FISHEYE",
    "ghost": "GraphicEffect.GHOST",
    "mosaic": "GraphicEffect.MOSAIC",
    "pixelate": "GraphicEffect.PIXELATE",
    "whirl": "GraphicEffect.WHIRL",
}

_ROTATION_STYLE_ENUMS = {
    "all around": "RotationStyle.ALL_AROUND",
    "left-right": "RotationStyle.LEFT_RIGHT",
    "left right": "RotationStyle.LEFT_RIGHT",
    "don't rotate": "RotationStyle.DONT_ROTATE",
    "dont rotate": "RotationStyle.DONT_ROTATE",
}

_LAYER_POSITION_ENUMS = {
    "back": "LayerPosition.BACK",
    "front": "LayerPosition.FRONT",
}

_LAYER_DIRECTION_ENUMS = {
    "backward": "LayerDirection.BACKWARD",
    "forward": "LayerDirection.FORWARD",
}

_STOP_TARGET_ENUMS = {
    "all": "StopTarget.ALL",
    "other scripts in sprite": "StopTarget.OTHER_SCRIPTS_IN_SPRITE",
    "this script": "StopTarget.THIS_SCRIPT",
}

_TARGET_DEFAULTS = {
    "x": 0.0,
    "y": 0.0,
    "direction": 90.0,
    "size": 100.0,
    "visible": True,
    "draggable": False,
    "rotation_style": "all around",
    "current_costume": 0,
    "volume": 100.0,
    "layer_order": 0,
    "tempo": 60.0,
    "video_transparency": 50.0,
    "video_state": "on",
    "text_to_speech_language": None,
}


class _NameAllocator:
    def __init__(self) -> None:
        self.used: set[str] = set()

    def alloc(self, raw: str, fallback: str) -> str:
        token = re.sub(r"\W+", "_", raw).strip("_").lower()
        if not token:
            token = fallback
        if token[0].isdigit():
            token = f"_{token}"
        if keyword.iskeyword(token):
            token = f"{token}_"
        candidate = token
        index = 2
        while candidate in self.used:
            candidate = f"{token}_{index}"
            index += 1
        self.used.add(candidate)
        return candidate


class _Exporter:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.parse_result = extract_scripts(project)
        self.targets_by_name = {target.name: target for target in project.targets}
        self.procedures_by_key = {(proc.target_name, proc.proccode): proc for proc in self.parse_result.procedures}
        self.target_aliases: dict[str, str] = {"Stage": "stage"}
        self.variable_aliases: dict[tuple[str, str], str] = {}
        self.list_aliases: dict[tuple[str, str], str] = {}
        self.procedure_names: dict[tuple[str, str], str] = {}
        self.procedure_param_names: dict[tuple[str, str], dict[str, str]] = {}
        self.script_names: dict[tuple[str, int], str] = {}
        self._validate()
        self._allocate_names()

    def _variable_alias(self, target_name: str, name: str) -> str:
        alias = self.variable_aliases.get((target_name, name))
        if alias is not None:
            return alias
        alias = self.variable_aliases.get(("Stage", name))
        if alias is not None:
            return alias
        raise CodegenError(f"Unknown exported variable on target {target_name!r}: {name!r}")

    def _list_alias(self, target_name: str, name: str) -> str:
        alias = self.list_aliases.get((target_name, name))
        if alias is not None:
            return alias
        alias = self.list_aliases.get(("Stage", name))
        if alias is not None:
            return alias
        raise CodegenError(f"Unknown exported list on target {target_name!r}: {name!r}")

    def _target_alias(self, target_name: str) -> str:
        alias = self.target_aliases.get(target_name)
        if alias is not None:
            return alias
        raise CodegenError(f"Unknown exported target: {target_name!r}")

    def _selector_constant(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        return _SPECIAL_SELECTOR_CONSTANTS.get(value.strip().lower())

    def _emit_selector(self, value: Any, target_name: str, proc_params: dict[str, str]) -> str:
        if isinstance(value, Expr):
            if value.kind == "literal":
                constant = self._selector_constant(value.value)
                if constant is not None:
                    return constant
            return self._emit_expr(value, target_name, proc_params)
        constant = self._selector_constant(value)
        if constant is not None:
            return constant
        return self._literal(value)

    def _enum_symbol(self, value: Any, mapping: dict[str, str]) -> str | None:
        if not isinstance(value, str):
            return None
        return mapping.get(value.strip().lower())

    def _effect_literal(self, value: Any) -> str:
        return self._enum_symbol(value, _EFFECT_ENUMS) or self._literal(value)

    def _rotation_style_literal(self, value: Any) -> str:
        return self._enum_symbol(value, _ROTATION_STYLE_ENUMS) or self._literal(value)

    def _layer_position_literal(self, value: Any) -> str:
        return self._enum_symbol(value, _LAYER_POSITION_ENUMS) or self._literal(value)

    def _layer_direction_literal(self, value: Any) -> str:
        return self._enum_symbol(value, _LAYER_DIRECTION_ENUMS) or self._literal(value)

    def _stop_target_literal(self, value: Any) -> str:
        return self._enum_symbol(value, _STOP_TARGET_ENUMS) or self._literal(value)

    def _validate(self) -> None:
        unsupported = [script for script in self.parse_result.scripts if not script.supported]
        if unsupported:
            first = unsupported[0]
            detail = first.unsupported_details[0] if first.unsupported_details else None
            reason = detail.reason if detail is not None else "unsupported_script"
            raise CodegenError(f"Cannot export unsupported script on target {first.target_name!r}: {reason}")

    def _allocate_names(self) -> None:
        global_names = _NameAllocator()
        global_names.used.add("stage")
        for target in self.project.targets:
            if target.is_stage:
                continue
            self.target_aliases[target.name] = global_names.alloc(target.name, "sprite")
        for target in self.project.targets:
            target_alias = self.target_aliases[target.name]
            for _, (name, _) in target.variables.items():
                fallback = f"{target_alias}_var" if not target.is_stage else "var"
                base = name if target.is_stage else f"{target_alias}_{name}"
                self.variable_aliases[(target.name, name)] = global_names.alloc(base, fallback)
            for _, (name, _) in target.lists.items():
                fallback = f"{target_alias}_list" if not target.is_stage else "list"
                base = name if target.is_stage else f"{target_alias}_{name}"
                self.list_aliases[(target.name, name)] = global_names.alloc(base, fallback)
        for procedure in self.parse_result.procedures:
            target_alias = self.target_aliases[procedure.target_name]
            base_name = procedure.proccode.replace("%s", " ").strip() or "procedure"
            fn_name = global_names.alloc(f"proc_{target_alias}_{base_name}", f"proc_{target_alias}")
            self.procedure_names[(procedure.target_name, procedure.proccode)] = fn_name
            param_names: dict[str, str] = {}
            param_allocator = _NameAllocator()
            for index, arg_id in enumerate(procedure.argument_ids, start=1):
                display = procedure.argument_names[index - 1] if index - 1 < len(procedure.argument_names) else f"arg{index}"
                param_names[arg_id] = param_allocator.alloc(display, f"arg{index}")
            self.procedure_param_names[(procedure.target_name, procedure.proccode)] = param_names
        per_target_counts: dict[str, int] = {}
        for script in self.parse_result.scripts:
            count = per_target_counts.get(script.target_name, 0) + 1
            per_target_counts[script.target_name] = count
            trigger = script.trigger.kind
            value = script.trigger.value or ""
            raw = f"on_{self.target_aliases[script.target_name]}_{trigger}_{value}_{count}"
            self.script_names[(script.target_name, count)] = global_names.alloc(raw, f"script_{count}")

    def render(self) -> str:
        info(_LOGGER, "codegen.exporter.render", "rendering project source targets=%d assets=%d", len(self.project.targets), len(self.project.assets))
        lines: list[str] = []
        if self.project.assets:
            lines.append("import base64")
            lines.append("")
        lines.append("from sb3vm.codegen import (")
        for name in _IMPORT_NAMES:
            lines.append(f"    {name},")
        lines.append(")")
        lines.append("")
        lines.append(f"project = ScratchProject({self._literal(self.project.meta.get('vm', 'Scratch Project'))})")
        lines.append("stage = project.stage")
        for extension in self.project.extensions:
            lines.append(f"project.extensions.append({self._literal(extension)})")
        for name in sorted({value for target in self.project.targets for value in target.broadcasts.values()}):
            lines.append(f"project.register_broadcast({self._literal(name)})")
        if self.project.assets:
            for name, payload in sorted(self.project.assets.items()):
                encoded = base64.b64encode(payload).decode("ascii")
                lines.append(f"project.add_asset({self._literal(name)}, base64.b64decode({self._literal(encoded)}))")
        if self.project.assets or self.project.extensions or any(target.broadcasts for target in self.project.targets):
            lines.append("")
        for target in self.project.targets:
            alias = self.target_aliases[target.name]
            trace(_LOGGER, "codegen.exporter.render", "emitting target %s as %s", target.name, alias)
            if target.is_stage:
                self._emit_target_properties(lines, alias, target)
            else:
                lines.append(
                    f"{alias} = project.sprite({self._literal(target.name)}, x={target.x!r}, y={target.y!r}, visible={target.visible!r}, current_costume={target.current_costume!r})"
                )
                self._emit_target_properties(lines, alias, target, skip={"x", "y", "visible", "current_costume"})
            for costume in target.costumes:
                lines.append(f"{alias}.add_costume({costume!r})")
            for sound in target.sounds:
                lines.append(f"{alias}.add_sound({sound!r})")
        if any(target.costumes or target.sounds or not target.is_stage for target in self.project.targets):
            lines.append("")
        for target in self.project.targets:
            for _, (name, default) in target.variables.items():
                alias = self.variable_aliases[(target.name, name)]
                target_alias = self.target_aliases[target.name]
                lines.append(f"{alias} = {target_alias}.variable({self._literal(name)}, {default!r})")
            for _, (name, values) in target.lists.items():
                alias = self.list_aliases[(target.name, name)]
                target_alias = self.target_aliases[target.name]
                lines.append(f"{alias} = {target_alias}.list({self._literal(name)}, {list(values)!r})")
        if self.variable_aliases or self.list_aliases:
            lines.append("")
        for procedure in self.parse_result.procedures:
            lines.extend(self._emit_procedure(procedure))
            lines.append("")
        counters: dict[str, int] = {}
        for script in self.parse_result.scripts:
            counters[script.target_name] = counters.get(script.target_name, 0) + 1
            lines.extend(self._emit_script(script, counters[script.target_name]))
            lines.append("")
        while lines and not lines[-1]:
            lines.pop()
        rendered = "\n".join(lines) + "\n"
        debug(_LOGGER, "codegen.exporter.render", "rendered source bytes=%d", len(rendered.encode("utf-8")))
        return rendered

    def _emit_target_properties(self, lines: list[str], alias: str, target: Target, *, skip: set[str] | None = None) -> None:
        skip = skip or set()
        values = {
            "x": target.x,
            "y": target.y,
            "direction": target.direction,
            "size": target.size,
            "visible": target.visible,
            "draggable": target.draggable,
            "rotation_style": target.rotation_style,
            "current_costume": target.current_costume,
            "volume": target.volume,
            "layer_order": target.layer_order,
            "tempo": target.tempo,
            "video_transparency": target.video_transparency,
            "video_state": target.video_state,
            "text_to_speech_language": target.text_to_speech_language,
        }
        for key, value in values.items():
            if key in skip:
                continue
            if value != _TARGET_DEFAULTS[key]:
                if key == "rotation_style":
                    lines.append(f"{alias}.{key} = {self._rotation_style_literal(value)}")
                else:
                    lines.append(f"{alias}.{key} = {value!r}")

    def _emit_procedure(self, procedure: ProcedureDefinition) -> list[str]:
        lines: list[str] = []
        target_alias = self.target_aliases[procedure.target_name]
        fn_name = self.procedure_names[(procedure.target_name, procedure.proccode)]
        param_map = self.procedure_param_names[(procedure.target_name, procedure.proccode)]
        params = [param_map[arg_id] for arg_id in procedure.argument_ids]
        lines.append(
            f"@{target_alias}.procedure(warp={procedure.warp!r}, proccode={self._literal(procedure.proccode)}, argument_names={tuple(procedure.argument_names)!r}, argument_defaults={tuple(procedure.argument_defaults)!r})"
        )
        lines.append(f"def {fn_name}({', '.join(params)}):")
        lines.extend(self._emit_body(procedure.body, procedure.target_name, param_map))
        return lines

    def _emit_script(self, script: Script, ordinal: int) -> list[str]:
        lines: list[str] = []
        target_alias = self.target_aliases[script.target_name]
        fn_name = self.script_names[(script.target_name, ordinal)]
        trigger = script.trigger
        if trigger.kind == "green_flag":
            lines.append(f"@{target_alias}.when_flag_clicked()")
        elif trigger.kind == "key_pressed":
            lines.append(f"@{target_alias}.when_key_pressed({self._literal(trigger.value or '')})")
        elif trigger.kind == "backdrop_switched":
            lines.append(f"@{target_alias}.when_backdrop_switched_to({self._literal(trigger.value or '')})")
        elif trigger.kind == "broadcast_received":
            lines.append(f"@{target_alias}.when_broadcast_received({self._literal(trigger.value or '')})")
        elif trigger.kind == "clone_start":
            lines.append(f"@{target_alias}.when_started_as_clone()")
        else:
            raise CodegenError(f"Unsupported trigger kind for export: {trigger.kind!r}")
        lines.append(f"def {fn_name}():")
        lines.extend(self._emit_body(script.body, script.target_name, {}))
        return lines

    def _emit_body(self, body: list[Stmt], target_name: str, proc_params: dict[str, str], indent: str = "    ") -> list[str]:
        if not body:
            return [f"{indent}pass"]
        lines: list[str] = []
        for stmt in body:
            lines.extend(self._emit_stmt(stmt, target_name, proc_params, indent))
        return lines

    def _emit_stmt(self, stmt: Stmt, target_name: str, proc_params: dict[str, str], indent: str) -> list[str]:
        kind = stmt.kind
        if kind == "set_var":
            return [f"{indent}{self._variable_alias(target_name, str(stmt.args['name']))} = {self._emit_expr(stmt.args['value'], target_name, proc_params)}"]
        if kind == "change_var":
            return [f"{indent}{self._variable_alias(target_name, str(stmt.args['name']))} += {self._emit_expr(stmt.args['value'], target_name, proc_params)}"]
        if kind == "list_add":
            return [f"{indent}{self._list_alias(target_name, str(stmt.args['name']))}.append({self._emit_expr(stmt.args['item'], target_name, proc_params)})"]
        if kind == "list_delete":
            return [f"{indent}{self._list_alias(target_name, str(stmt.args['name']))}.delete({self._emit_expr(stmt.args['index'], target_name, proc_params)})"]
        if kind == "list_delete_all":
            return [f"{indent}{self._list_alias(target_name, str(stmt.args['name']))}.clear()"]
        if kind == "list_insert":
            return [f"{indent}{self._list_alias(target_name, str(stmt.args['name']))}.insert({self._emit_expr(stmt.args['index'], target_name, proc_params)}, {self._emit_expr(stmt.args['item'], target_name, proc_params)})"]
        if kind == "list_replace":
            return [f"{indent}{self._list_alias(target_name, str(stmt.args['name']))}.replace({self._emit_expr(stmt.args['index'], target_name, proc_params)}, {self._emit_expr(stmt.args['item'], target_name, proc_params)})"]
        if kind == "wait":
            return [f"{indent}{self._target_alias(target_name)}.wait({self._emit_expr(stmt.args['duration'], target_name, proc_params)})"]
        if kind == "repeat":
            lines = [f"{indent}for _ in range({self._emit_expr(stmt.args['times'], target_name, proc_params)}):"]
            lines.extend(self._emit_body(stmt.args['body'], target_name, proc_params, indent + '    '))
            return lines
        if kind == "forever":
            lines = [f"{indent}while True:"]
            lines.extend(self._emit_body(stmt.args['body'], target_name, proc_params, indent + '    '))
            return lines
        if kind == "if":
            lines = [f"{indent}if {self._emit_expr(stmt.args['condition'], target_name, proc_params)}:"]
            lines.extend(self._emit_body(stmt.args['body'], target_name, proc_params, indent + '    '))
            return lines
        if kind == "if_else":
            lines = [f"{indent}if {self._emit_expr(stmt.args['condition'], target_name, proc_params)}:"]
            lines.extend(self._emit_body(stmt.args['body'], target_name, proc_params, indent + '    '))
            lines.append(f"{indent}else:")
            lines.extend(self._emit_body(stmt.args['else_body'], target_name, proc_params, indent + '    '))
            return lines
        if kind == "repeat_until":
            lines = [f"{indent}while not {self._emit_expr(stmt.args['condition'], target_name, proc_params)}:"]
            lines.extend(self._emit_body(stmt.args['body'], target_name, proc_params, indent + '    '))
            return lines
        if kind == "broadcast":
            fn = 'broadcast_wait' if stmt.args['wait'] else 'broadcast'
            return [f"{indent}{self._target_alias(target_name)}.{fn}({self._literal(stmt.args['name'])})"]
        if kind == "stop":
            return [f"{indent}{self._target_alias(target_name)}.stop({self._stop_target_literal(stmt.args['mode'])})"]
        if kind == "move_state":
            mode = stmt.args['mode']
            target_alias = self._target_alias(target_name)
            mapping = {
                'goto_xy': lambda: f"{target_alias}.goto_xy({self._emit_expr(stmt.args['x'], target_name, proc_params)}, {self._emit_expr(stmt.args['y'], target_name, proc_params)})",
                'goto_target': lambda: f"{target_alias}.goto_target({self._emit_selector(stmt.args['target'], target_name, proc_params)})",
                'glide_xy': lambda: f"{target_alias}.glide_xy({self._emit_expr(stmt.args['duration'], target_name, proc_params)}, {self._emit_expr(stmt.args['x'], target_name, proc_params)}, {self._emit_expr(stmt.args['y'], target_name, proc_params)})",
                'glide_target': lambda: f"{target_alias}.glide_to({self._emit_expr(stmt.args['duration'], target_name, proc_params)}, {self._emit_selector(stmt.args['target'], target_name, proc_params)})",
                'set_x': lambda: f"{target_alias}.set_x({self._emit_expr(stmt.args['x'], target_name, proc_params)})",
                'set_y': lambda: f"{target_alias}.set_y({self._emit_expr(stmt.args['y'], target_name, proc_params)})",
                'change_x': lambda: f"{target_alias}.change_x_by({self._emit_expr(stmt.args['dx'], target_name, proc_params)})",
                'change_y': lambda: f"{target_alias}.change_y_by({self._emit_expr(stmt.args['dy'], target_name, proc_params)})",
                'turn_right': lambda: f"{target_alias}.turn_right({self._emit_expr(stmt.args['degrees'], target_name, proc_params)})",
                'turn_left': lambda: f"{target_alias}.turn_left({self._emit_expr(stmt.args['degrees'], target_name, proc_params)})",
                'point_direction': lambda: f"{target_alias}.point_in_direction({self._emit_expr(stmt.args['direction'], target_name, proc_params)})",
                'point_towards': lambda: f"{target_alias}.point_towards({self._emit_selector(stmt.args['target'], target_name, proc_params)})",
                'set_rotation_style': lambda: f"{target_alias}.set_rotation_style({self._rotation_style_literal(stmt.args['style'])})",
            }
            return [f"{indent}{mapping[mode]()}"]
        if kind == "looks_state":
            mode = stmt.args['mode']
            target_alias = self._target_alias(target_name)
            mapping = {
                'show': lambda: f'{target_alias}.show()',
                'hide': lambda: f'{target_alias}.hide()',
                'switch_costume': lambda: f"{target_alias}.switch_costume({self._emit_expr(stmt.args['costume'], target_name, proc_params)})",
                'next_costume': lambda: f'{target_alias}.next_costume()',
                'switch_backdrop': lambda: f"{target_alias}.{'switch_backdrop_wait' if stmt.args['wait'] else 'switch_backdrop'}({self._emit_expr(stmt.args['backdrop'], target_name, proc_params)})",
                'next_backdrop': lambda: f'{target_alias}.next_backdrop()',
                'set_size': lambda: f"{target_alias}.set_size({self._emit_expr(stmt.args['size'], target_name, proc_params)})",
                'change_size': lambda: f"{target_alias}.change_size_by({self._emit_expr(stmt.args['delta'], target_name, proc_params)})",
                'set_effect': lambda: f"{target_alias}.set_effect({self._effect_literal(stmt.args['effect'])}, {self._emit_expr(stmt.args['value'], target_name, proc_params)})",
                'change_effect': lambda: f"{target_alias}.change_effect_by({self._effect_literal(stmt.args['effect'])}, {self._emit_expr(stmt.args['value'], target_name, proc_params)})",
                'clear_effects': lambda: f'{target_alias}.clear_graphic_effects()',
                'go_front_back': lambda: f"{target_alias}.go_front_back({self._layer_position_literal(stmt.args['direction'])})",
                'go_layers': lambda: f"{target_alias}.go_layers({self._layer_direction_literal(stmt.args['direction'])}, {self._emit_expr(stmt.args['layers'], target_name, proc_params)})",
            }
            if mode == 'dialogue':
                if 'duration' in stmt.args:
                    fn = 'say_for_secs' if stmt.args['style'] == 'say' else 'think_for_secs'
                    return [f"{indent}{target_alias}.{fn}({self._emit_expr(stmt.args['message'], target_name, proc_params)}, {self._emit_expr(stmt.args['duration'], target_name, proc_params)})"]
                fn = 'say' if stmt.args['style'] == 'say' else 'think'
                return [f"{indent}{target_alias}.{fn}({self._emit_expr(stmt.args['message'], target_name, proc_params)})"]
            return [f"{indent}{mapping[mode]()}"]
        if kind == "create_clone":
            return [f"{indent}{self._target_alias(target_name)}.create_clone({self._emit_selector(stmt.args['selector'], target_name, proc_params)})"]
        if kind == "delete_clone":
            return [f"{indent}{self._target_alias(target_name)}.delete_this_clone()"]
        if kind == "ask":
            return [f"{indent}{self._target_alias(target_name)}.ask({self._emit_expr(stmt.args['prompt'], target_name, proc_params)})"]
        if kind == "reset_timer":
            return [f"{indent}{self._target_alias(target_name)}.reset_timer()"]
        if kind == "music_play_note":
            return [f"{indent}{self._target_alias(target_name)}.play_note_for_beats({self._emit_expr(stmt.args['note'], target_name, proc_params)}, {self._emit_expr(stmt.args['beats'], target_name, proc_params)})"]
        if kind == "proc_call":
            proc = self.procedures_by_key[(target_name, stmt.args['proccode'])]
            fn_name = self.procedure_names[(target_name, stmt.args['proccode'])]
            args = [self._emit_expr(stmt.args['arguments'][arg_id], target_name, proc_params) for arg_id in proc.argument_ids]
            return [f"{indent}{fn_name}({', '.join(args)})"]
        raise CodegenError(f"Unsupported exported statement kind: {kind!r}")

    def _emit_value(self, value: Any, target_name: str, proc_params: dict[str, str]) -> str:
        return self._emit_expr(value, target_name, proc_params) if isinstance(value, Expr) else self._literal(value)

    def _emit_expr(self, expr: Expr, target_name: str, proc_params: dict[str, str]) -> str:
        kind = expr.kind
        if kind == 'literal':
            return self._literal(expr.value)
        if kind == 'var':
            return self._variable_alias(target_name, str(expr.value))
        if kind == 'proc_arg':
            return proc_params[str(expr.value)]
        if kind == 'list_item':
            return f"{self._list_alias(target_name, str(expr.value['name']))}.item({self._emit_expr(expr.value['index'], target_name, proc_params)})"
        if kind == 'list_length':
            return f"{self._list_alias(target_name, str(expr.value))}.length()"
        if kind == 'list_contains':
            return f"{self._list_alias(target_name, str(expr.value['name']))}.contains({self._emit_expr(expr.value['item'], target_name, proc_params)})"
        if kind == 'list_contents':
            return f"{self._list_alias(target_name, str(expr.value))}.contents()"
        if kind in {'operator_add', 'operator_subtract', 'operator_multiply', 'operator_divide', 'operator_mod', 'operator_equals', 'operator_lt', 'operator_gt'}:
            op = {
                'operator_add': '+',
                'operator_subtract': '-',
                'operator_multiply': '*',
                'operator_divide': '/',
                'operator_mod': '%',
                'operator_equals': '==',
                'operator_lt': '<',
                'operator_gt': '>',
            }[kind]
            return f"({self._emit_expr(expr.args[0], target_name, proc_params)} {op} {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'operator_and':
            return f"({self._emit_expr(expr.args[0], target_name, proc_params)} and {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'operator_or':
            return f"({self._emit_expr(expr.args[0], target_name, proc_params)} or {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'operator_not':
            return f"(not {self._emit_expr(expr.args[0], target_name, proc_params)})"
        if kind == 'operator_join':
            return f"join({self._emit_expr(expr.args[0], target_name, proc_params)}, {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'operator_letter_of':
            return f"letter_of({self._emit_expr(expr.args[0], target_name, proc_params)}, {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'operator_length':
            return f"string_length({self._emit_expr(expr.args[0], target_name, proc_params)})"
        if kind == 'operator_contains':
            return f"string_contains({self._emit_expr(expr.args[0], target_name, proc_params)}, {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'operator_round':
            return f"round_value({self._emit_expr(expr.args[0], target_name, proc_params)})"
        if kind == 'operator_mathop':
            return f"math_op({self._literal(expr.value)}, {self._emit_expr(expr.args[0], target_name, proc_params)})"
        if kind == 'operator_random':
            return f"random_between({self._emit_expr(expr.args[0], target_name, proc_params)}, {self._emit_expr(expr.args[1], target_name, proc_params)})"
        if kind == 'timer':
            return 'timer()'
        if kind == 'answer':
            return 'answer()'
        if kind == 'key_pressed':
            return f"key_pressed({self._emit_expr(expr.args[0], target_name, proc_params)})"
        if kind == 'mouse_x':
            return 'mouse_x()'
        if kind == 'mouse_y':
            return 'mouse_y()'
        if kind == 'mouse_down':
            return 'mouse_down()'
        if kind == 'touching_object':
            return f"{self._target_alias(target_name)}.touching_object({self._emit_selector(expr.args[0], target_name, proc_params)})"
        if kind == 'x_position':
            return f"{self._target_alias(target_name)}.x_position()"
        if kind == 'y_position':
            return f"{self._target_alias(target_name)}.y_position()"
        if kind == 'direction':
            return f"{self._target_alias(target_name)}.direction_value()"
        if kind == 'size':
            return f"{self._target_alias(target_name)}.size_value()"
        if kind == 'costume_info':
            return f"{self._target_alias(target_name)}.costume_name()" if str(expr.value) == 'name' else f"{self._target_alias(target_name)}.costume_number()"
        if kind == 'backdrop_info':
            return f"{self._target_alias(target_name)}.backdrop_name()" if str(expr.value) == 'name' else f"{self._target_alias(target_name)}.backdrop_number()"
        raise CodegenError(f"Unsupported exported expression kind: {kind!r}")

    def _literal(self, value: Any) -> str:
        return repr(value)


def export_project_source(project: Project) -> str:
    info(_LOGGER, "codegen.export_project_source", "exporting project source targets=%d", len(project.targets))
    return _Exporter(project).render()


def save_project_source(source: Project | str | Path, output: str | Path) -> str:
    project = source if isinstance(source, Project) else load_sb3(source)
    rendered = export_project_source(project)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding='utf-8')
    info(_LOGGER, "codegen.save_project_source", "saved exported source to %s", output_path)
    return rendered
