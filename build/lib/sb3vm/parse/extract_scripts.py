from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sb3vm.model.project import Project, Target
from sb3vm.parse.ast_nodes import Expr, ProcedureDefinition, Script, Stmt, Trigger, UnsupportedDiagnostic
from sb3vm.vm.errors import ProjectValidationError

SUPPORTED_EVENT_OPS = {
    "event_whenflagclicked",
    "event_whenbroadcastreceived",
    "control_start_as_clone",
}

ARG_REPORTER_OPS = {
    "argument_reporter_string_number",
    "argument_reporter_boolean",
}

SUPPORTED_EXPR_OPS = {
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
    "sensing_timer",
    "sensing_answer",
    "sensing_keypressed",
    "sensing_keyoptions",
    "sensing_mousex",
    "sensing_mousey",
    "sensing_mousedown",
    "motion_xposition",
    "motion_yposition",
    "motion_direction",
    "looks_size",
    "looks_costumenumbername",
    "looks_backdropnumbername",
    "data_variable",
    "data_itemoflist",
    "data_lengthoflist",
    "data_listcontainsitem",
    "data_contentsoflist",
    *ARG_REPORTER_OPS,
    "control_create_clone_of_menu",
}

SUPPORTED_STMT_OPS = {
    "event_broadcast",
    "event_broadcastandwait",
    "control_wait",
    "control_repeat",
    "control_forever",
    "control_if",
    "control_if_else",
    "control_repeat_until",
    "control_stop",
    "data_setvariableto",
    "data_changevariableby",
    "data_addtolist",
    "data_deleteoflist",
    "data_deletealloflist",
    "data_insertatlist",
    "data_replaceitemoflist",
    "motion_gotoxy",
    "motion_goto",
    "motion_glidesecstoxy",
    "motion_glideto",
    "motion_setx",
    "motion_sety",
    "motion_changexby",
    "motion_changeyby",
    "motion_turnright",
    "motion_turnleft",
    "motion_pointindirection",
    "motion_pointtowards",
    "looks_show",
    "looks_hide",
    "looks_switchcostumeto",
    "looks_nextcostume",
    "looks_switchbackdropto",
    "looks_switchbackdroptoandwait",
    "looks_nextbackdrop",
    "looks_setsizeto",
    "looks_changesizeby",
    "looks_seteffectto",
    "looks_changeeffectby",
    "looks_cleargraphiceffects",
    "looks_gotofrontback",
    "looks_goforwardbackwardlayers",
    "motion_setrotationstyle",
    "procedures_call",
    "control_create_clone_of",
    "control_delete_this_clone",
    "sensing_askandwait",
    "sensing_resettimer",
}


@dataclass
class ParseResult:
    scripts: list[Script]
    procedures: list[ProcedureDefinition]
    opcode_histogram: Counter[str]
    supported_opcode_histogram: Counter[str]
    unsupported_opcode_histogram: Counter[str]
    diagnostics: list[UnsupportedDiagnostic] = field(default_factory=list)

    def opcode_coverage(self) -> dict[str, Any]:
        all_opcodes = sorted(self.opcode_histogram)
        supported = {opcode: self.supported_opcode_histogram[opcode] for opcode in sorted(self.supported_opcode_histogram)}
        unsupported = {opcode: self.unsupported_opcode_histogram[opcode] for opcode in sorted(self.unsupported_opcode_histogram)}
        return {
            "total_seen": sum(self.opcode_histogram.values()),
            "supported_seen": sum(self.supported_opcode_histogram.values()),
            "unsupported_seen": sum(self.unsupported_opcode_histogram.values()),
            "unique_total": len(all_opcodes),
            "unique_supported": len(supported),
            "unique_unsupported": len(unsupported),
            "by_opcode": {opcode: self.opcode_histogram[opcode] for opcode in all_opcodes},
            "supported_by_opcode": supported,
            "unsupported_by_opcode": unsupported,
        }


def extract_scripts(project: Project) -> ParseResult:
    parser = ProjectParser(project)
    return parser.parse()


class ProjectParser:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.opcode_histogram: Counter[str] = Counter()
        self.supported_opcode_histogram: Counter[str] = Counter()
        self.unsupported_opcode_histogram: Counter[str] = Counter()
        self.procedures_by_target: dict[str, dict[str, ProcedureDefinition]] = {}
        self.diagnostics: list[UnsupportedDiagnostic] = []

    def parse(self) -> ParseResult:
        for target in self.project.targets:
            self._collect_opcodes(target)
            self._collect_procedures(target)

        scripts: list[Script] = []
        for target in self.project.targets:
            for block_id, block in target.blocks.items():
                self._validate_block_record(target, block_id, block)
                opcode = block.get("opcode")
                if not block.get("topLevel"):
                    continue
                if opcode not in SUPPORTED_EVENT_OPS:
                    continue
                trigger = self.parse_trigger(block)
                body = self.parse_stmt_chain(target, block.get("next"))
                script = Script(target_name=target.name, trigger=trigger, body=body)
                unsupported = self.find_unsupported(script)
                if trigger.kind == "clone_start" and target.is_stage:
                    unsupported.append(
                        UnsupportedDiagnostic(
                            target_name=target.name,
                            trigger_kind=trigger.kind,
                            trigger_value=trigger.value,
                            node_kind="statement",
                            opcode=str(opcode),
                            reason="clone start hat is not valid on stage",
                            block_id=block_id,
                        )
                    )
                if unsupported:
                    script.supported = False
                    script.unsupported_details = unsupported
                scripts.append(script)

        procedures = [
            proc
            for target_procedures in self.procedures_by_target.values()
            for proc in target_procedures.values()
        ]
        return ParseResult(
            scripts=scripts,
            procedures=sorted(procedures, key=lambda proc: (proc.target_name, proc.proccode)),
            opcode_histogram=self.opcode_histogram,
            supported_opcode_histogram=self.supported_opcode_histogram,
            unsupported_opcode_histogram=self.unsupported_opcode_histogram,
            diagnostics=list(self.diagnostics),
        )

    def _collect_opcodes(self, target: Target) -> None:
        for block_id, block in target.blocks.items():
            self._validate_block_record(target, block_id, block)
            opcode = block.get("opcode")
            if not opcode:
                continue
            self.opcode_histogram[opcode] += 1
            if opcode in SUPPORTED_EVENT_OPS or opcode in SUPPORTED_STMT_OPS or opcode in SUPPORTED_EXPR_OPS or opcode in {
                "procedures_definition",
                "procedures_prototype",
            }:
                self.supported_opcode_histogram[opcode] += 1
            else:
                self.unsupported_opcode_histogram[opcode] += 1

    def _collect_procedures(self, target: Target) -> None:
        procedures: dict[str, ProcedureDefinition] = {}
        for block_id, block in target.blocks.items():
            if block.get("opcode") != "procedures_definition":
                continue
            try:
                procedure = self.parse_procedure_signature(target, block_id, block)
            except ProjectValidationError:
                raise
            except ValueError as exc:
                self.diagnostics.append(
                    UnsupportedDiagnostic(
                        target_name=target.name,
                        trigger_kind="procedure_definition",
                        trigger_value=None,
                        node_kind="statement",
                        opcode="procedures_definition",
                        reason=str(exc),
                        block_id=block_id,
                    )
                )
                continue
            procedures[procedure.proccode] = procedure
        self.procedures_by_target[target.name] = procedures
        for procedure in procedures.values():
            definition_block = target.blocks[procedure.block_id or ""]
            arg_map = {name: arg_id for arg_id, name in zip(procedure.argument_ids, procedure.argument_names)}
            procedure.body = self.parse_stmt_chain(target, definition_block.get("next"), procedure_args=arg_map)

    def parse_procedure_signature(self, target: Target, block_id: str, block: dict[str, Any]) -> ProcedureDefinition:
        prototype_id = self.extract_input_block_id(
            block.get("inputs", {}).get("custom_block"),
            target.name,
            block_id,
            "custom_block",
        )
        prototype = target.blocks.get(prototype_id)
        if prototype is None:
            raise ProjectValidationError(
                "Missing procedure prototype block",
                target_name=target.name,
                block_id=prototype_id,
                reference="custom_block",
            )
        self._validate_block_record(target, prototype_id, prototype)
        if prototype.get("opcode") != "procedures_prototype":
            raise ValueError("procedure definition does not reference a procedures_prototype block")
        mutation = self._mutation_dict(prototype)
        proccode = self._mutation_str(mutation, "proccode")
        if not proccode:
            raise ValueError("procedure definition is missing a proccode")

        argument_ids = self._mutation_json_list(mutation, "argumentids")
        argument_names = [str(item) for item in self._mutation_json_list(mutation, "argumentnames")]
        argument_defaults = self._mutation_json_list(mutation, "argumentdefaults")
        if len(argument_ids) != len(argument_names):
            raise ValueError("procedure definition argument ids/names length mismatch")
        if argument_defaults and len(argument_defaults) != len(argument_ids):
            raise ValueError("procedure definition defaults length mismatch")
        if not argument_defaults:
            argument_defaults = ["" for _ in argument_ids]
        return ProcedureDefinition(
            target_name=target.name,
            proccode=proccode,
            argument_ids=argument_ids,
            argument_names=argument_names,
            argument_defaults=argument_defaults,
            warp=self._mutation_bool(mutation, "warp"),
            body=[],
            block_id=block_id,
        )

    def parse_trigger(self, block: dict[str, Any]) -> Trigger:
        opcode = block.get("opcode")
        if opcode == "event_whenflagclicked":
            return Trigger("green_flag")
        if opcode == "event_whenbroadcastreceived":
            return Trigger("broadcast_received", self.field_value(block, "BROADCAST_OPTION"))
        if opcode == "control_start_as_clone":
            return Trigger("clone_start")
        return Trigger("unknown")

    def parse_stmt_chain(
        self,
        target: Target,
        start_block_id: str | None,
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> list[Stmt]:
        stmts: list[Stmt] = []
        block_id = start_block_id
        seen: set[str] = set()
        while block_id:
            if block_id in seen:
                raise ProjectValidationError(
                    "Detected cycle while traversing script chain",
                    target_name=target.name,
                    block_id=block_id,
                    reference="next",
                )
            seen.add(block_id)
            block = target.blocks.get(block_id)
            if not block:
                raise ProjectValidationError(
                    "Missing referenced block in script chain",
                    target_name=target.name,
                    block_id=block_id,
                    reference="next",
                )
            stmts.append(self.parse_stmt(target, block_id, block, procedure_args=procedure_args))
            block_id = self._optional_block_reference(target, block_id, block.get("next"), "next")
        return stmts

    def parse_stmt(
        self,
        target: Target,
        block_id: str,
        block: dict[str, Any],
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> Stmt:
        opcode = block.get("opcode", "")
        f = self.field_value
        expr = lambda key: self.parse_input_expr(target, block_id, block, key, procedure_args=procedure_args)
        stack = lambda key: self.parse_substack(target, block_id, block, key, procedure_args=procedure_args)
        if opcode == "data_setvariableto":
            return Stmt("set_var", {"name": f(block, "VARIABLE"), "value": expr("VALUE")})
        if opcode == "data_changevariableby":
            return Stmt("change_var", {"name": f(block, "VARIABLE"), "value": expr("VALUE")})
        if opcode == "data_addtolist":
            return Stmt("list_add", {"name": f(block, "LIST"), "item": expr("ITEM")})
        if opcode == "data_deleteoflist":
            return Stmt("list_delete", {"name": f(block, "LIST"), "index": expr("INDEX")})
        if opcode == "data_deletealloflist":
            return Stmt("list_delete_all", {"name": f(block, "LIST")})
        if opcode == "data_insertatlist":
            return Stmt("list_insert", {"name": f(block, "LIST"), "index": expr("INDEX"), "item": expr("ITEM")})
        if opcode == "data_replaceitemoflist":
            return Stmt("list_replace", {"name": f(block, "LIST"), "index": expr("INDEX"), "item": expr("ITEM")})
        if opcode == "control_wait":
            return Stmt("wait", {"duration": expr("DURATION")})
        if opcode == "control_repeat":
            return Stmt("repeat", {"times": expr("TIMES"), "body": stack("SUBSTACK")})
        if opcode == "control_forever":
            return Stmt("forever", {"body": stack("SUBSTACK")})
        if opcode == "control_if":
            return Stmt("if", {"condition": expr("CONDITION"), "body": stack("SUBSTACK")})
        if opcode == "control_if_else":
            return Stmt("if_else", {"condition": expr("CONDITION"), "body": stack("SUBSTACK"), "else_body": stack("SUBSTACK2")})
        if opcode == "control_repeat_until":
            return Stmt("repeat_until", {"condition": expr("CONDITION"), "body": stack("SUBSTACK")})
        if opcode == "control_stop":
            return Stmt("stop", {"mode": f(block, "STOP_OPTION") or "this script"})
        if opcode == "event_broadcast":
            return Stmt("broadcast", {"name": self.broadcast_name(target, block, procedure_args=procedure_args), "wait": False})
        if opcode == "event_broadcastandwait":
            return Stmt("broadcast", {"name": self.broadcast_name(target, block, procedure_args=procedure_args), "wait": True})
        if opcode == "motion_gotoxy":
            return Stmt("move_state", {"mode": "goto_xy", "x": expr("X"), "y": expr("Y")})
        if opcode == "motion_goto":
            return Stmt("move_state", {"mode": "goto_target", "target": expr("TO")})
        if opcode == "motion_glidesecstoxy":
            return Stmt("move_state", {"mode": "glide_xy", "duration": expr("SECS"), "x": expr("X"), "y": expr("Y")})
        if opcode == "motion_glideto":
            return Stmt("move_state", {"mode": "glide_target", "duration": expr("SECS"), "target": expr("TO")})
        if opcode == "motion_setx":
            return Stmt("move_state", {"mode": "set_x", "x": expr("X")})
        if opcode == "motion_sety":
            return Stmt("move_state", {"mode": "set_y", "y": expr("Y")})
        if opcode == "motion_changexby":
            return Stmt("move_state", {"mode": "change_x", "dx": expr("DX")})
        if opcode == "motion_changeyby":
            return Stmt("move_state", {"mode": "change_y", "dy": expr("DY")})
        if opcode == "motion_turnright":
            return Stmt("move_state", {"mode": "turn_right", "degrees": expr("DEGREES")})
        if opcode == "motion_turnleft":
            return Stmt("move_state", {"mode": "turn_left", "degrees": expr("DEGREES")})
        if opcode == "motion_pointindirection":
            return Stmt("move_state", {"mode": "point_direction", "direction": expr("DIRECTION")})
        if opcode == "motion_pointtowards":
            return Stmt("move_state", {"mode": "point_towards", "target": expr("TOWARDS")})
        if opcode == "motion_setrotationstyle":
            return Stmt("move_state", {"mode": "set_rotation_style", "style": f(block, "STYLE") or ""})
        if opcode == "looks_show":
            return Stmt("looks_state", {"mode": "show"})
        if opcode == "looks_hide":
            return Stmt("looks_state", {"mode": "hide"})
        if opcode == "looks_switchcostumeto":
            return Stmt("looks_state", {"mode": "switch_costume", "costume": expr("COSTUME")})
        if opcode == "looks_nextcostume":
            return Stmt("looks_state", {"mode": "next_costume"})
        if opcode == "looks_switchbackdropto":
            return Stmt("looks_state", {"mode": "switch_backdrop", "backdrop": expr("BACKDROP")})
        if opcode == "looks_switchbackdroptoandwait":
            return Stmt("looks_state", {"mode": "switch_backdrop", "backdrop": expr("BACKDROP")})
        if opcode == "looks_nextbackdrop":
            return Stmt("looks_state", {"mode": "next_backdrop"})
        if opcode == "looks_setsizeto":
            return Stmt("looks_state", {"mode": "set_size", "size": expr("SIZE")})
        if opcode == "looks_changesizeby":
            return Stmt("looks_state", {"mode": "change_size", "delta": expr("CHANGE")})
        if opcode == "looks_seteffectto":
            return Stmt("looks_state", {"mode": "set_effect", "effect": f(block, "EFFECT") or "", "value": expr("VALUE")})
        if opcode == "looks_changeeffectby":
            return Stmt("looks_state", {"mode": "change_effect", "effect": f(block, "EFFECT") or "", "value": expr("CHANGE")})
        if opcode == "looks_cleargraphiceffects":
            return Stmt("looks_state", {"mode": "clear_effects"})
        if opcode == "looks_gotofrontback":
            return Stmt("looks_state", {"mode": "go_front_back", "direction": f(block, "FRONT_BACK") or ""})
        if opcode == "looks_goforwardbackwardlayers":
            return Stmt("looks_state", {"mode": "go_layers", "direction": f(block, "FORWARD_BACKWARD") or "", "layers": expr("NUM")})
        if opcode == "procedures_call":
            return self.parse_procedure_call(target, block_id, block, procedure_args=procedure_args)
        if opcode == "control_create_clone_of":
            return Stmt("create_clone", {"selector": self.parse_clone_selector(target, block_id, block, procedure_args=procedure_args)})
        if opcode == "control_delete_this_clone":
            return Stmt("delete_clone", {})
        if opcode == "sensing_askandwait":
            return Stmt("ask", {"prompt": expr("QUESTION")})
        if opcode == "sensing_resettimer":
            return Stmt("reset_timer", {})
        return Stmt("unsupported", {"opcode": opcode, "block_id": block_id})

    def parse_procedure_call(
        self,
        target: Target,
        block_id: str,
        block: dict[str, Any],
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> Stmt:
        mutation = self._mutation_dict(block)
        proccode = self._mutation_str(mutation, "proccode")
        if not proccode:
            return Stmt("unsupported", {"opcode": "procedures_call", "block_id": block_id})
        procedure = self.procedures_by_target.get(target.name, {}).get(proccode)
        if procedure is None:
            return Stmt("unsupported", {"opcode": "procedures_call", "block_id": block_id})
        arguments = {
            arg_id: self.parse_input_expr(target, block_id, block, arg_id, procedure_args=procedure_args)
            for arg_id in procedure.argument_ids
            if arg_id in block.get("inputs", {})
        }
        return Stmt("proc_call", {"proccode": proccode, "arguments": arguments})

    def parse_substack(
        self,
        target: Target,
        block_id: str,
        block: dict[str, Any],
        key: str,
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> list[Stmt]:
        input_value = block.get("inputs", {}).get(key)
        if input_value is None:
            return []
        ref_block_id = self.extract_input_block_id(input_value, target.name, block_id, key)
        return self.parse_stmt_chain(target, ref_block_id, procedure_args=procedure_args)

    def parse_input_expr(
        self,
        target: Target,
        block_id: str,
        block: dict[str, Any],
        key: str,
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> Expr:
        return self.parse_expr(
            target,
            block.get("inputs", {}).get(key),
            source_block_id=block_id,
            source_ref=key,
            procedure_args=procedure_args,
        )

    def parse_expr(
        self,
        target: Target,
        input_value: Any,
        *,
        source_block_id: str | None = None,
        source_ref: str | None = None,
        procedure_args: dict[str, str] | None = None,
    ) -> Expr:
        if input_value is None:
            return Expr("literal", None)
        if isinstance(input_value, str):
            if input_value in target.blocks:
                return self.parse_expr_from_block(target, input_value, target.blocks[input_value], procedure_args=procedure_args)
            return Expr("literal", input_value)
        if isinstance(input_value, list):
            if len(input_value) >= 2:
                candidate = input_value[1]
                if isinstance(candidate, str) and candidate in target.blocks:
                    return self.parse_expr_from_block(target, candidate, target.blocks[candidate], procedure_args=procedure_args)
                if isinstance(candidate, list):
                    return self.parse_literal(candidate)
                if candidate is None and len(input_value) >= 3 and isinstance(input_value[2], list):
                    return self.parse_literal(input_value[2])
                if isinstance(candidate, str):
                    return Expr("literal", candidate)
            if len(input_value) == 2 and isinstance(input_value[0], int):
                return self.parse_literal(input_value)
            raise ProjectValidationError(
                "Malformed input value",
                target_name=target.name,
                block_id=source_block_id,
                reference=source_ref,
            )
        if isinstance(input_value, (int, float, bool)):
            return Expr("literal", input_value)
        return Expr("literal", None)

    def parse_literal(self, value: list[Any]) -> Expr:
        if len(value) < 2:
            return Expr("literal", None)
        literal = value[1]
        if isinstance(literal, str):
            maybe = literal.strip()
            if maybe:
                try:
                    if "." in maybe:
                        return Expr("literal", float(maybe))
                    return Expr("literal", int(maybe))
                except ValueError:
                    return Expr("literal", literal)
        return Expr("literal", literal)

    def parse_expr_from_block(
        self,
        target: Target,
        block_id: str,
        block: dict[str, Any],
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> Expr:
        self._validate_block_record(target, block_id, block)
        opcode = block.get("opcode", "")
        if opcode == "data_variable":
            return Expr("var", self.field_value(block, "VARIABLE"))
        if opcode == "data_itemoflist":
            return Expr("list_item", {"name": self.field_value(block, "LIST"), "index": self.parse_input_expr(target, block_id, block, "INDEX", procedure_args=procedure_args)})
        if opcode == "data_lengthoflist":
            return Expr("list_length", self.field_value(block, "LIST"))
        if opcode == "data_listcontainsitem":
            return Expr("list_contains", {"name": self.field_value(block, "LIST"), "item": self.parse_input_expr(target, block_id, block, "ITEM", procedure_args=procedure_args)})
        if opcode == "data_contentsoflist":
            return Expr("list_contents", self.field_value(block, "LIST"))
        if opcode in {"operator_add", "operator_subtract", "operator_multiply", "operator_divide", "operator_mod", "operator_equals", "operator_lt", "operator_gt"}:
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "NUM1", procedure_args=procedure_args), self.parse_input_expr(target, block_id, block, "NUM2", procedure_args=procedure_args)])
        if opcode in {"operator_and", "operator_or", "operator_join", "operator_contains"}:
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "OPERAND1", procedure_args=procedure_args), self.parse_input_expr(target, block_id, block, "OPERAND2", procedure_args=procedure_args)])
        if opcode == "operator_not":
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "OPERAND", procedure_args=procedure_args)])
        if opcode == "operator_random":
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "FROM", procedure_args=procedure_args), self.parse_input_expr(target, block_id, block, "TO", procedure_args=procedure_args)])
        if opcode == "operator_letter_of":
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "LETTER", procedure_args=procedure_args), self.parse_input_expr(target, block_id, block, "STRING", procedure_args=procedure_args)])
        if opcode == "operator_length":
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "STRING", procedure_args=procedure_args)])
        if opcode == "operator_round":
            return Expr(opcode, args=[self.parse_input_expr(target, block_id, block, "NUM", procedure_args=procedure_args)])
        if opcode == "operator_mathop":
            return Expr(opcode, value=self.field_value(block, "OPERATOR") or "abs", args=[self.parse_input_expr(target, block_id, block, "NUM", procedure_args=procedure_args)])
        if opcode == "sensing_timer":
            return Expr("timer")
        if opcode == "sensing_answer":
            return Expr("answer")
        if opcode == "sensing_keypressed":
            return Expr("key_pressed", args=[self.parse_input_expr(target, block_id, block, "KEY_OPTION", procedure_args=procedure_args)])
        if opcode == "sensing_keyoptions":
            return Expr("literal", self.field_value(block, "KEY_OPTION") or "")
        if opcode == "sensing_mousex":
            return Expr("mouse_x")
        if opcode == "sensing_mousey":
            return Expr("mouse_y")
        if opcode == "sensing_mousedown":
            return Expr("mouse_down")
        if opcode == "motion_xposition":
            return Expr("x_position")
        if opcode == "motion_yposition":
            return Expr("y_position")
        if opcode == "motion_direction":
            return Expr("direction")
        if opcode == "looks_size":
            return Expr("size")
        if opcode == "looks_costumenumbername":
            return Expr("costume_info", self.field_value(block, "NUMBER_NAME") or "number")
        if opcode == "looks_backdropnumbername":
            return Expr("backdrop_info", self.field_value(block, "NUMBER_NAME") or "number")
        if opcode == "control_create_clone_of_menu":
            return Expr("literal", self.field_value(block, "CLONE_OPTION") or "")
        if opcode in ARG_REPORTER_OPS:
            arg_name = self.field_value(block, "VALUE") or self.field_value(block, "TEXT")
            if arg_name and procedure_args and arg_name in procedure_args:
                return Expr("proc_arg", procedure_args[arg_name])
            return Expr("unsupported", opcode)
        return Expr("unsupported", opcode)

    def parse_clone_selector(
        self,
        target: Target,
        block_id: str,
        block: dict[str, Any],
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> str:
        field = self.field_value(block, "CLONE_OPTION")
        if field:
            return field
        selector_expr = self.parse_expr(
            target,
            block.get("inputs", {}).get("CLONE_OPTION"),
            source_block_id=block_id,
            source_ref="CLONE_OPTION",
            procedure_args=procedure_args,
        )
        if selector_expr.kind == "literal":
            return "" if selector_expr.value is None else str(selector_expr.value)
        return ""

    def extract_input_block_id(self, input_value: Any, target_name: str, source_block_id: str | None, reference: str) -> str:
        if isinstance(input_value, str):
            return input_value
        if isinstance(input_value, list) and len(input_value) >= 2 and isinstance(input_value[1], str):
            return input_value[1]
        raise ProjectValidationError(
            "Malformed block reference input",
            target_name=target_name,
            block_id=source_block_id,
            reference=reference,
        )

    def field_value(self, block: dict[str, Any], key: str) -> str | None:
        field = block.get("fields", {}).get(key)
        if not field:
            return None
        if isinstance(field, list) and field:
            return field[0]
        return None

    def broadcast_name(
        self,
        target: Target,
        block: dict[str, Any],
        *,
        procedure_args: dict[str, str] | None = None,
    ) -> str:
        input_expr = self.parse_expr(target, block.get("inputs", {}).get("BROADCAST_INPUT"), source_ref="BROADCAST_INPUT", procedure_args=procedure_args)
        if input_expr.kind == "literal" and input_expr.value not in (None, ""):
            return str(input_expr.value)
        field = self.field_value(block, "BROADCAST_OPTION")
        return field or ""

    def find_unsupported(self, script: Script) -> list[UnsupportedDiagnostic]:
        reasons: list[UnsupportedDiagnostic] = []

        def visit_expr(expr: Expr) -> None:
            if expr.kind == "unsupported":
                reasons.append(
                    UnsupportedDiagnostic(
                        target_name=script.target_name,
                        trigger_kind=script.trigger.kind,
                        trigger_value=script.trigger.value,
                        node_kind="expression",
                        opcode=str(expr.value),
                        reason="unsupported expression opcode",
                    )
                )
            for arg in expr.args:
                visit_expr(arg)
            if isinstance(expr.value, dict):
                for item in expr.value.values():
                    if isinstance(item, Expr):
                        visit_expr(item)

        def visit_stmt(stmt: Stmt) -> None:
            if stmt.kind == "unsupported":
                reasons.append(
                    UnsupportedDiagnostic(
                        target_name=script.target_name,
                        trigger_kind=script.trigger.kind,
                        trigger_value=script.trigger.value,
                        node_kind="statement",
                        opcode=str(stmt.args.get("opcode", "")),
                        reason="unsupported statement opcode",
                        block_id=stmt.args.get("block_id"),
                    )
                )
            for value in stmt.args.values():
                if isinstance(value, Expr):
                    visit_expr(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, Stmt):
                            visit_stmt(item)
                        elif isinstance(item, Expr):
                            visit_expr(item)
                elif isinstance(value, dict):
                    for item in value.values():
                        if isinstance(item, Expr):
                            visit_expr(item)

        for stmt in script.body:
            visit_stmt(stmt)
        unique: dict[tuple[str, str, str | None], UnsupportedDiagnostic] = {}
        for item in reasons:
            unique[(item.node_kind, item.opcode, item.block_id)] = item
        return [unique[key] for key in sorted(unique)]

    def _optional_block_reference(self, target: Target, source_block_id: str, candidate: Any, reference: str) -> str | None:
        if candidate is None:
            return None
        if not isinstance(candidate, str):
            raise ProjectValidationError(
                "Block reference must be a string or null",
                target_name=target.name,
                block_id=source_block_id,
                reference=reference,
            )
        if candidate not in target.blocks:
            raise ProjectValidationError(
                "Missing referenced block in script chain",
                target_name=target.name,
                block_id=candidate,
                reference=reference,
            )
        return candidate

    def _validate_block_record(self, target: Target, block_id: str, block: dict[str, Any]) -> None:
        if not isinstance(block.get("opcode"), str) or not block["opcode"]:
            raise ProjectValidationError("Block is missing a valid opcode", target_name=target.name, block_id=block_id)
        inputs = block.get("inputs", {})
        fields = block.get("fields", {})
        mutation = block.get("mutation")
        if inputs is not None and not isinstance(inputs, dict):
            raise ProjectValidationError("Block field 'inputs' must be an object", target_name=target.name, block_id=block_id)
        if fields is not None and not isinstance(fields, dict):
            raise ProjectValidationError("Block field 'fields' must be an object", target_name=target.name, block_id=block_id)
        if mutation is not None and not isinstance(mutation, dict):
            raise ProjectValidationError("Block field 'mutation' must be an object", target_name=target.name, block_id=block_id)

    def _mutation_dict(self, block: dict[str, Any]) -> dict[str, Any]:
        mutation = block.get("mutation", {})
        if mutation is None:
            return {}
        if not isinstance(mutation, dict):
            raise ProjectValidationError("Block field 'mutation' must be an object")
        return mutation

    def _mutation_str(self, mutation: dict[str, Any], key: str) -> str:
        value = mutation.get(key, "")
        return str(value) if value is not None else ""

    def _mutation_json_list(self, mutation: dict[str, Any], key: str) -> list[Any]:
        raw = mutation.get(key)
        if raw in (None, ""):
            return []
        if isinstance(raw, list):
            return list(raw)
        if not isinstance(raw, str):
            raise ValueError(f"procedure mutation field '{key}' must be a JSON string")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"procedure mutation field '{key}' is not valid JSON") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"procedure mutation field '{key}' must decode to a list")
        return parsed

    def _mutation_bool(self, mutation: dict[str, Any], key: str) -> bool:
        raw = mutation.get(key, False)
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() == "true"
