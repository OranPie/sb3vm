from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from sb3vm.model.project import Project
from sb3vm.parse.ast_nodes import AskState, RuntimeDiagnostic, Script, Stmt
from sb3vm.parse.extract_scripts import extract_scripts
from sb3vm.vm.compiler import CompiledScript, compile_script
from sb3vm.vm.eval_expr import eval_expr
from sb3vm.vm.input_provider import HeadlessInputProvider, InputProvider, VmRng
from sb3vm.vm.ir import IrScript, lower_script
from sb3vm.vm.scratch_values import compare_equal, compare_order, letter_of, resolve_insert_index, resolve_list_index, to_bool, to_number
from sb3vm.vm.state import FrameState, LoopState, ThreadState, VMState


@dataclass
class RunResult:
    vm_state: VMState
    scripts: list[Script]


@dataclass
class VmConfig:
    max_call_depth: int = 100
    max_clones: int = 300
    random_seed: int | None = None
    enable_compilation: bool = False
    lazy_compile_threshold: int | None = None


class Sb3Vm:
    def __init__(
        self,
        project: Project,
        *,
        max_call_depth: int = 100,
        max_clones: int = 300,
        random_seed: int | None = None,
        enable_compilation: bool = False,
        lazy_compile_threshold: int | None = None,
        input_provider: InputProvider | None = None,
    ) -> None:
        self.project = project
        self.config = VmConfig(
            max_call_depth=max_call_depth,
            max_clones=max_clones,
            random_seed=random_seed,
            enable_compilation=enable_compilation,
            lazy_compile_threshold=lazy_compile_threshold,
        )
        self.input_provider: InputProvider = input_provider or HeadlessInputProvider()
        self.rng = VmRng(random_seed)
        self.parsed = extract_scripts(project)
        self.scripts = self.parsed.scripts
        self.procedures = {
            (procedure.target_name, procedure.proccode): procedure
            for procedure in self.parsed.procedures
        }
        self.opcode_histogram = self.parsed.opcode_histogram
        self.ir_scripts: dict[str, IrScript] = {
            f"{index}:{script.target_name}:{script.trigger.kind}:{script.trigger.value or ''}": lower_script(
                script,
                f"{index}:{script.target_name}:{script.trigger.kind}:{script.trigger.value or ''}",
            )
            for index, script in enumerate(self.scripts)
        }
        self._script_keys_by_identity = {
            id(script): key
            for key, script in zip(self.ir_scripts, self.scripts)
        }
        self._compiled_scripts: dict[str, CompiledScript] = {}
        self._script_runs: dict[str, int] = {key: 0 for key in self.ir_scripts}
        self.state = VMState.from_project(project)
        self._next_thread_id = 1
        self._next_spawn_order = 1
        self._next_instance_id = max(self.state.instances, default=0) + 1
        self._pending_instance_deletions: set[int] = set()

    def timer_seconds(self) -> float:
        return self.state.timer_seconds(self.input_provider.timer_override(self.state.time_seconds))

    def random_index(self, length: int) -> int:
        return self.rng.randrange(length)

    def snapshot(self) -> dict[str, Any]:
        provider_state = self.input_provider.snapshot()
        provider_state["timer_seconds"] = self.timer_seconds()
        return self.state.snapshot(input_state=provider_state, random_seed=self.config.random_seed)

    def render_snapshot(self) -> dict[str, Any]:
        return self.state.render_snapshot(self.project)

    def inspect(self) -> dict[str, Any]:
        unsupported = [
            diagnostic.to_dict()
            for script in self.scripts
            if not script.supported
            for diagnostic in script.unsupported_details
        ]
        unsupported.extend(diagnostic.to_dict() for diagnostic in self.parsed.diagnostics)
        return {
            "targets": [t.name for t in self.project.targets],
            "script_count": len(self.scripts),
            "opcode_histogram": dict(self.opcode_histogram),
            "opcode_coverage": self.parsed.opcode_coverage(),
            "procedures": [procedure.to_dict() for procedure in self.parsed.procedures],
            "clone_script_count": len([script for script in self.scripts if script.trigger.kind == "clone_start"]),
            "script_capabilities": {
                key: {
                    "compile_safe": ir_script.compile_safe,
                    "reason": ir_script.compile_reason,
                    "compiled": key in self._compiled_scripts,
                    "runs": self._script_runs.get(key, 0),
                }
                for key, ir_script in sorted(self.ir_scripts.items())
            },
            "unsupported_scripts": unsupported,
        }

    def run_for(self, seconds: float, dt: float = 1 / 30) -> RunResult:
        self.start_green_flag()
        steps = max(0, int(seconds / dt))
        for _ in range(steps):
            self.step(dt)
        return RunResult(self.state, self.scripts)

    def start_green_flag(self) -> None:
        for script in self.scripts:
            if script.trigger.kind != "green_flag":
                continue
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            self._spawn_for_matching_instances(script, include_clones=False)

    def emit_broadcast(self, name: str, wait_parent: ThreadState | None = None) -> set[int]:
        child_ids: set[int] = set()
        for script in self.scripts:
            if script.trigger.kind != "broadcast_received" or script.trigger.value != name:
                continue
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids |= self._spawn_for_matching_instances(script, include_clones=True)
        if wait_parent is not None:
            wait_parent.waiting_for_children |= child_ids
            wait_parent.wait_reason = f"broadcast:{name}"
        return child_ids

    def _spawn_clone_start(self, instance_id: int) -> set[int]:
        child_ids: set[int] = set()
        source_target_name = self.state.get_instance(instance_id).source_target_name
        for script in self.scripts:
            if script.target_name != source_target_name or script.trigger.kind != "clone_start":
                continue
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids.add(self._spawn_script(script, instance_id).id)
        return child_ids

    def _spawn_for_matching_instances(self, script: Script, *, include_clones: bool) -> set[int]:
        child_ids: set[int] = set()
        for instance in self.state.instances.values():
            if instance.source_target_name != script.target_name:
                continue
            if instance.is_clone and not include_clones:
                continue
            child_ids.add(self._spawn_script(script, instance.instance_id).id)
        return child_ids

    def _spawn_script(self, script: Script, instance_id: int) -> ThreadState:
        script_key = self._script_keys_by_identity[id(script)]
        compiled = self._compiled_for_key(script_key)
        tid = self._next_thread_id
        self._next_thread_id += 1
        thread = ThreadState(
            id=tid,
            instance_id=instance_id,
            root_target_name=script.target_name,
            root_trigger=script.trigger.kind,
            spawn_order=self._next_spawn_order,
            engine="compiled" if compiled is not None else "interpreted",
            script_key=script_key,
            frames=[FrameState(kind="compiled", stmts=[])] if compiled is not None else [FrameState(kind="script", stmts=script.body)],
        )
        if compiled is not None:
            thread.compiled_runner = compiled.generator_factory(self, thread)
        self._next_spawn_order += 1
        self.state.threads[tid] = thread
        return thread

    def step(self, dt: float) -> None:
        self.state.time_seconds += dt
        active_ids = sorted(self.state.threads, key=lambda tid: self.state.threads[tid].spawn_order)
        for thread_id in active_ids:
            thread = self.state.threads.get(thread_id)
            if thread is None or thread.done:
                continue
            if thread.instance_id in self._pending_instance_deletions:
                thread.done = True
                continue
            if thread.waiting_for_answer is not None:
                answer = self.input_provider.pop_answer()
                if answer is None:
                    continue
                self.input_provider.set_answer(answer)
                thread.waiting_for_answer = None
            if thread.waiting_for_children:
                alive = {tid for tid in thread.waiting_for_children if tid in self.state.threads and not self.state.threads[tid].done}
                thread.waiting_for_children = alive
                if alive:
                    continue
                thread.wait_reason = None
            if thread.glide is not None:
                if self._update_glide(thread):
                    continue
            if thread.wake_time > self.state.time_seconds:
                continue
            if thread.compiled_runner is not None:
                self._advance_compiled_thread(thread)
                continue
            self._advance_thread(thread)
        for tid in [tid for tid, thread in self.state.threads.items() if thread.done]:
            self.state.threads.pop(tid, None)
        for instance_id in list(self._pending_instance_deletions):
            self.state.instances.pop(instance_id, None)
            self._pending_instance_deletions.discard(instance_id)

    def _advance_thread(self, thread: ThreadState) -> None:
        executed = 0
        while not thread.done:
            if thread.instance_id in self._pending_instance_deletions:
                thread.done = True
                return
            if thread.waiting_for_answer is not None:
                return
            if not thread.frames:
                thread.done = True
                return
            frame = thread.frames[-1]
            if frame.kind == "repeat_loop":
                if frame.loop is None:
                    thread.frames.pop()
                    continue
                if frame.loop.remaining is not None and frame.loop.remaining <= 0:
                    thread.frames.pop()
                    continue
                if frame.loop.remaining is not None:
                    frame.loop.remaining -= 1
                thread.frames.append(FrameState(kind="sequence", stmts=frame.loop.body))
                continue
            if frame.kind == "forever_loop":
                if frame.loop is None:
                    thread.frames.pop()
                    continue
                thread.frames.append(FrameState(kind="sequence", stmts=frame.loop.body))
                continue
            if frame.kind == "repeat_until_loop":
                if frame.loop is None:
                    thread.frames.pop()
                    continue
                if to_bool(eval_expr(frame.loop.condition, self.state, thread, self)):
                    thread.frames.pop()
                    continue
                thread.frames.append(FrameState(kind="sequence", stmts=frame.loop.body))
                continue
            if frame.index >= len(frame.stmts):
                popped = thread.frames.pop()
                if popped.kind == "sequence" and thread.frames and thread.frames[-1].kind in {"repeat_loop", "repeat_until_loop", "forever_loop"}:
                    if not thread.in_warp():
                        return
                continue

            stmt = frame.stmts[frame.index]
            frame.index += 1
            action = self._execute_stmt(thread, stmt)
            if action == "yield":
                return
            if action == "block":
                return
            executed += 1
            if not thread.in_warp() and executed >= 1:
                return

    def _advance_compiled_thread(self, thread: ThreadState) -> None:
        if thread.compiled_runner is None:
            return
        try:
            action = next(thread.compiled_runner)
        except StopIteration:
            thread.done = True
            return
        if action == "block":
            return
        if action == "yield":
            return

    def _execute_stmt(self, thread: ThreadState, stmt: Stmt) -> str | None:
        instance = self.state.get_instance(thread.instance_id)
        kind = stmt.kind
        if kind == "set_var":
            self._set_var(thread.instance_id, stmt.args["name"], eval_expr(stmt.args["value"], self.state, thread, self))
            return None
        if kind == "change_var":
            cur = self._get_var(thread.instance_id, stmt.args["name"])
            value = to_number(cur) + to_number(eval_expr(stmt.args["value"], self.state, thread, self))
            self._set_var(thread.instance_id, stmt.args["name"], value)
            return None
        if kind == "list_add":
            self._get_list(thread.instance_id, stmt.args["name"]).append(eval_expr(stmt.args["item"], self.state, thread, self))
            return None
        if kind == "list_delete":
            lst = self._get_list(thread.instance_id, stmt.args["name"])
            idx = resolve_list_index(eval_expr(stmt.args["index"], self.state, thread, self), len(lst), random_index=self.random_index)
            if idx is not None:
                del lst[idx]
            return None
        if kind == "list_delete_all":
            self._get_list(thread.instance_id, stmt.args["name"]).clear()
            return None
        if kind == "list_insert":
            lst = self._get_list(thread.instance_id, stmt.args["name"])
            idx = resolve_insert_index(eval_expr(stmt.args["index"], self.state, thread, self), len(lst), random_index=self.random_index)
            lst.insert(idx, eval_expr(stmt.args["item"], self.state, thread, self))
            return None
        if kind == "list_replace":
            lst = self._get_list(thread.instance_id, stmt.args["name"])
            idx = resolve_list_index(eval_expr(stmt.args["index"], self.state, thread, self), len(lst), random_index=self.random_index)
            if idx is not None:
                lst[idx] = eval_expr(stmt.args["item"], self.state, thread, self)
            return None
        if kind == "wait":
            thread.wake_time = self.state.time_seconds + max(0.0, to_number(eval_expr(stmt.args["duration"], self.state, thread, self)))
            return "block"
        if kind == "repeat":
            times = int(to_number(eval_expr(stmt.args["times"], self.state, thread, self)))
            if times > 0:
                thread.frames.append(FrameState(kind="repeat_loop", stmts=[], loop=LoopState(kind="repeat", body=stmt.args["body"], remaining=times)))
            return None
        if kind == "forever":
            thread.frames.append(FrameState(kind="forever_loop", stmts=[], loop=LoopState(kind="forever", body=stmt.args["body"])))
            return None
        if kind == "if":
            if to_bool(eval_expr(stmt.args["condition"], self.state, thread, self)):
                thread.frames.append(FrameState(kind="sequence", stmts=stmt.args["body"]))
            return None
        if kind == "if_else":
            branch = stmt.args["body"] if to_bool(eval_expr(stmt.args["condition"], self.state, thread, self)) else stmt.args["else_body"]
            if branch:
                thread.frames.append(FrameState(kind="sequence", stmts=branch))
            return None
        if kind == "repeat_until":
            thread.frames.append(FrameState(kind="repeat_until_loop", stmts=[], loop=LoopState(kind="repeat_until", body=stmt.args["body"], condition=stmt.args["condition"])))
            return None
        if kind == "broadcast":
            child_ids = self.emit_broadcast(str(stmt.args["name"]), wait_parent=thread if stmt.args["wait"] else None)
            if stmt.args["wait"] and child_ids:
                return "block"
            return None
        if kind == "stop":
            return self._handle_stop(thread, str(stmt.args["mode"]).lower())
        if kind == "move_state":
            mode = stmt.args["mode"]
            values = {
                key: eval_expr(value, self.state, thread, self) if hasattr(value, "kind") else value
                for key, value in stmt.args.items()
                if key != "mode"
            }
            return self._execute_move_state(thread, mode, values)
        if kind == "looks_state":
            mode = stmt.args["mode"]
            values = {
                key: eval_expr(value, self.state, thread, self) if hasattr(value, "kind") else value
                for key, value in stmt.args.items()
                if key != "mode"
            }
            return self._execute_looks_state(thread, mode, values)
        if kind == "proc_call":
            return self._call_procedure(thread, stmt.args["proccode"], stmt.args["arguments"])
        if kind == "create_clone":
            self._create_clone(thread, str(stmt.args["selector"]))
            return None
        if kind == "delete_clone":
            return self._delete_clone(thread)
        if kind == "ask":
            prompt = str(eval_expr(stmt.args["prompt"], self.state, thread, self))
            answer = self.input_provider.pop_answer()
            if answer is None:
                thread.waiting_for_answer = AskState(prompt=prompt)
                return "block"
            self.input_provider.set_answer(answer)
            return None
        if kind == "reset_timer":
            self.state.reset_timer()
            return None
        if kind == "unsupported":
            thread.done = True
            return "block"
        raise ValueError(f"Unsupported statement kind: {kind}")

    def _handle_stop(self, thread: ThreadState, mode: str) -> str:
        if mode == "all":
            for other in self.state.threads.values():
                other.waiting_for_children.clear()
                other.wait_reason = None
                other.done = True
            return "block"
        if mode == "other scripts in sprite":
            for other in self.state.threads.values():
                if other.instance_id == thread.instance_id and other.id != thread.id:
                    other.done = True
            return None
        thread.done = True
        return "block"

    def _call_procedure(self, thread: ThreadState, proccode: str, arguments: dict[str, Any]) -> str | None:
        source_target_name = self.state.get_instance(thread.instance_id).source_target_name
        procedure = self.procedures.get((source_target_name, proccode))
        if procedure is None:
            self.state.runtime_diagnostics.append(
                RuntimeDiagnostic(
                    kind="missing_procedure",
                    message=f"Unknown procedure: {proccode}",
                    target_name=source_target_name,
                    thread_id=thread.id,
                    proccode=proccode,
                    instance_id=thread.instance_id,
                )
            )
            thread.done = True
            return "block"

        if thread.call_depth() + 1 > self.config.max_call_depth:
            self.state.runtime_diagnostics.append(
                RuntimeDiagnostic(
                    kind="recursion_limit",
                    message=f"Procedure call depth exceeded limit {self.config.max_call_depth}",
                    target_name=source_target_name,
                    thread_id=thread.id,
                    proccode=proccode,
                    depth=thread.call_depth() + 1,
                    instance_id=thread.instance_id,
                )
            )
            thread.done = True
            return "block"

        bound_arguments = {
            arg_id: eval_expr(expr, self.state, thread, self)
            for arg_id, expr in arguments.items()
        }
        for arg_id, default in zip(procedure.argument_ids, procedure.argument_defaults):
            bound_arguments.setdefault(arg_id, default)
        thread.frames.append(
            FrameState(
                kind="procedure",
                stmts=procedure.body,
                arguments=bound_arguments,
                proccode=proccode,
                warp=procedure.warp,
            )
        )
        return None

    def _create_clone(self, thread: ThreadState, selector: str) -> None:
        source_instance = self.state.get_instance(thread.instance_id)
        if selector == "myself":
            base_instance = source_instance
        else:
            if selector not in self.state.original_instance_ids:
                self.state.runtime_diagnostics.append(
                    RuntimeDiagnostic(
                        kind="invalid_clone_target",
                        message=f"Unknown clone target: {selector}",
                        target_name=source_instance.source_target_name,
                        thread_id=thread.id,
                        instance_id=thread.instance_id,
                    )
                )
                return
            base_instance = self.state.get_instance(self.state.get_original_instance_id(selector))
        if base_instance.is_stage:
            self.state.runtime_diagnostics.append(
                RuntimeDiagnostic(
                    kind="invalid_clone_target",
                    message=f"Cannot clone target: {selector or base_instance.source_target_name}",
                    target_name=source_instance.source_target_name,
                    thread_id=thread.id,
                    instance_id=thread.instance_id,
                )
            )
            return
        if self.state.live_clone_count() >= self.config.max_clones:
            self.state.runtime_diagnostics.append(
                RuntimeDiagnostic(
                    kind="clone_limit",
                    message=f"Clone limit {self.config.max_clones} reached",
                    target_name=base_instance.source_target_name,
                    thread_id=thread.id,
                    instance_id=thread.instance_id,
                )
            )
            return

        new_instance = replace(
            base_instance,
            instance_id=self._next_instance_id,
            local_variables=dict(base_instance.local_variables),
            local_lists={name: list(values) for name, values in base_instance.local_lists.items()},
            is_clone=True,
        )
        self.state.instances[self._next_instance_id] = new_instance
        self._next_instance_id += 1
        self._spawn_clone_start(new_instance.instance_id)

    def _delete_clone(self, thread: ThreadState) -> str:
        instance = self.state.get_instance(thread.instance_id)
        if not instance.is_clone:
            self.state.runtime_diagnostics.append(
                RuntimeDiagnostic(
                    kind="delete_non_clone",
                    message="delete this clone called on a non-clone instance",
                    target_name=instance.source_target_name,
                    thread_id=thread.id,
                    instance_id=thread.instance_id,
                )
            )
            return None
        self._pending_instance_deletions.add(thread.instance_id)
        for other in self.state.threads.values():
            if other.instance_id == thread.instance_id:
                other.done = True
        return "block"

    def _get_var(self, instance_id: int, name: str) -> Any:
        target = self.state.get_instance(instance_id)
        if name in target.local_variables:
            return target.local_variables[name]
        return self.state.stage_variables.get(name, 0)

    def _set_var(self, instance_id: int, name: str, value: Any) -> None:
        target = self.state.get_instance(instance_id)
        if name in target.local_variables or name not in self.state.stage_variables:
            target.local_variables[name] = value
            if target.is_stage:
                self.state.stage_variables[name] = value
        else:
            self.state.stage_variables[name] = value

    def _get_list(self, instance_id: int, name: str) -> list[Any]:
        target = self.state.get_instance(instance_id)
        if name in target.local_lists or name not in self.state.stage_lists:
            return target.local_lists.setdefault(name, [])
        return self.state.stage_lists.setdefault(name, [])

    def _resolve_insert_index_value(self, index: Any, length: int) -> int:
        return resolve_insert_index(index, length, random_index=self.random_index)

    def _normalize_direction(self, value: float) -> float:
        normalized = ((value + 180.0) % 360.0) - 180.0
        if normalized == -180.0:
            return 180.0
        return normalized

    def _normalize_rotation_style(self, value: str) -> str:
        lowered = value.strip().lower()
        aliases = {
            "all around": "all around",
            "left-right": "left-right",
            "left right": "left-right",
            "don't rotate": "don't rotate",
            "dont rotate": "don't rotate",
        }
        return aliases.get(lowered, value or "all around")

    def _normalize_effect_name(self, value: str) -> str:
        return value.strip().lower()

    def _compare_equal(self, left: Any, right: Any) -> bool:
        return compare_equal(left, right)

    def _compare_order(self, left: Any, right: Any, op: str) -> bool:
        lhs, rhs = compare_order(left, right)
        if op == "<":
            return lhs < rhs
        return lhs > rhs

    def _letter_of(self, index: Any, value: Any) -> str:
        return letter_of(index, value)

    def _apply_mathop(self, op: str, value: float) -> float:
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
        return value

    def _resolve_target_position(self, selector: Any, instance: Any) -> tuple[float, float]:
        text = str(selector).strip()
        lowered = text.lower()
        if lowered == "_mouse_":
            return self.input_provider.mouse_x(), self.input_provider.mouse_y()
        if lowered == "_random_":
            return self.rng.uniform(-240.0, 240.0), self.rng.uniform(-180.0, 180.0)
        if text in self.state.original_instance_ids:
            original = self.state.get_instance(self.state.get_original_instance_id(text))
            return original.x, original.y
        return instance.x, instance.y

    def _execute_move_state(self, thread: ThreadState, mode: str, values: dict[str, Any]) -> str | None:
        instance = self.state.get_instance(thread.instance_id)
        if mode == "goto_xy":
            instance.x = to_number(values["x"])
            instance.y = to_number(values["y"])
        elif mode == "goto_target":
            instance.x, instance.y = self._resolve_target_position(values["target"], instance)
        elif mode == "glide_xy":
            return self._start_glide(thread, instance, to_number(values["x"]), to_number(values["y"]), values["duration"])
        elif mode == "glide_target":
            target_x, target_y = self._resolve_target_position(values["target"], instance)
            return self._start_glide(thread, instance, target_x, target_y, values["duration"])
        elif mode == "set_x":
            instance.x = to_number(values["x"])
        elif mode == "set_y":
            instance.y = to_number(values["y"])
        elif mode == "change_x":
            instance.x += to_number(values["dx"])
        elif mode == "change_y":
            instance.y += to_number(values["dy"])
        elif mode == "turn_right":
            instance.direction = self._normalize_direction(instance.direction + to_number(values["degrees"]))
        elif mode == "turn_left":
            instance.direction = self._normalize_direction(instance.direction - to_number(values["degrees"]))
        elif mode == "point_direction":
            instance.direction = self._normalize_direction(to_number(values["direction"]))
        elif mode == "point_towards":
            target_x, target_y = self._resolve_target_position(values["target"], instance)
            dx = target_x - instance.x
            dy = target_y - instance.y
            if dx != 0 or dy != 0:
                instance.direction = self._normalize_direction(90.0 - math.degrees(math.atan2(dy, dx)))
        elif mode == "set_rotation_style":
            instance.rotation_style = self._normalize_rotation_style(str(values["style"]))
        return None

    def _execute_looks_state(self, thread: ThreadState, mode: str, values: dict[str, Any]) -> str | None:
        instance = self.state.get_instance(thread.instance_id)
        if mode == "show":
            instance.visible = True
        elif mode == "hide":
            instance.visible = False
        elif mode == "switch_costume":
            self._switch_costume(instance, values["costume"])
        elif mode == "next_costume":
            self._advance_costume(instance, 1)
        elif mode == "switch_backdrop":
            self._switch_backdrop(values["backdrop"])
        elif mode == "next_backdrop":
            self._advance_backdrop(1)
        elif mode == "set_size":
            instance.size = max(0.0, to_number(values["size"]))
        elif mode == "change_size":
            instance.size = max(0.0, instance.size + to_number(values["delta"]))
        elif mode == "set_effect":
            effect_name = self._normalize_effect_name(str(values["effect"]))
            instance.effects[effect_name] = to_number(values["value"])
        elif mode == "change_effect":
            effect_name = self._normalize_effect_name(str(values["effect"]))
            instance.effects[effect_name] = instance.effects.get(effect_name, 0.0) + to_number(values["value"])
        elif mode == "clear_effects":
            instance.effects.clear()
        elif mode == "go_front_back":
            self._move_layer_extreme(instance, str(values["direction"]))
        elif mode == "go_layers":
            self._move_layer_relative(instance, str(values["direction"]), int(to_number(values["layers"])))
        return None

    def _compiled_for_key(self, script_key: str) -> CompiledScript | None:
        self._script_runs[script_key] = self._script_runs.get(script_key, 0) + 1
        if not self.config.enable_compilation:
            return None
        ir_script = self.ir_scripts[script_key]
        if not ir_script.compile_safe:
            return None
        threshold = self.config.lazy_compile_threshold
        if threshold is not None and self._script_runs[script_key] < threshold:
            return None
        compiled = self._compiled_scripts.get(script_key)
        if compiled is None:
            compiled = compile_script(ir_script)
            self._compiled_scripts[script_key] = compiled
        return compiled

    def _start_glide(self, thread: ThreadState, instance: Any, target_x: float, target_y: float, duration_value: Any) -> str:
        duration = max(0.0, to_number(duration_value))
        if duration <= 0.0:
            instance.x = target_x
            instance.y = target_y
            return None
        thread.glide = {
            "start_time": self.state.time_seconds,
            "duration": duration,
            "from_x": instance.x,
            "from_y": instance.y,
            "to_x": target_x,
            "to_y": target_y,
        }
        return "block"

    def _update_glide(self, thread: ThreadState) -> bool:
        glide = thread.glide
        if glide is None:
            return False
        instance = self.state.get_instance(thread.instance_id)
        elapsed = max(0.0, self.state.time_seconds - glide["start_time"])
        duration = max(glide["duration"], 1e-9)
        progress = min(1.0, elapsed / duration)
        instance.x = glide["from_x"] + (glide["to_x"] - glide["from_x"]) * progress
        instance.y = glide["from_y"] + (glide["to_y"] - glide["from_y"]) * progress
        if progress < 1.0:
            return True
        thread.glide = None
        return False

    def _target_costumes(self, target_name: str) -> list[dict[str, Any]]:
        return self.project.get_target(target_name).costumes

    def _stage_instance(self) -> Any:
        return self.state.get_instance(self.state.get_original_instance_id("Stage"))

    def _resolve_costume_index(self, target_name: str, value: Any) -> int | None:
        costumes = self._target_costumes(target_name)
        if not costumes:
            return None
        if isinstance(value, (int, float)):
            return min(max(int(value) - 1, 0), len(costumes) - 1)
        name = str(value)
        names = [str(costume.get("name", "")) for costume in costumes]
        if name in names:
            return names.index(name)
        return None

    def _switch_costume(self, instance: Any, value: Any) -> None:
        index = self._resolve_costume_index(instance.source_target_name, value)
        if index is not None:
            instance.costume_index = index

    def _advance_costume(self, instance: Any, delta: int) -> None:
        costumes = self._target_costumes(instance.source_target_name)
        if costumes:
            instance.costume_index = (instance.costume_index + delta) % len(costumes)

    def _switch_backdrop(self, value: Any) -> None:
        stage = self._stage_instance()
        index = self._resolve_costume_index(stage.source_target_name, value)
        if index is not None:
            stage.costume_index = index

    def _advance_backdrop(self, delta: int) -> None:
        stage = self._stage_instance()
        self._advance_costume(stage, delta)

    def _reindex_layers(self, ordered_instances: list[Any]) -> None:
        for index, current in enumerate(ordered_instances):
            current.layer_order = index

    def _ordered_instances(self) -> list[Any]:
        return sorted(self.state.instances.values(), key=lambda item: (item.layer_order, item.instance_id))

    def _move_layer_extreme(self, instance: Any, direction: str) -> None:
        ordered = self._ordered_instances()
        ordered = [item for item in ordered if item.instance_id != instance.instance_id]
        lowered = direction.strip().lower()
        if lowered == "front":
            ordered.append(instance)
        else:
            ordered.insert(0, instance)
        self._reindex_layers(ordered)

    def _move_layer_relative(self, instance: Any, direction: str, amount: int) -> None:
        if amount <= 0:
            return
        ordered = self._ordered_instances()
        current_index = next(index for index, item in enumerate(ordered) if item.instance_id == instance.instance_id)
        ordered.pop(current_index)
        delta = amount if direction.strip().lower() == "forward" else -amount
        new_index = min(max(current_index + delta, 0), len(ordered))
        ordered.insert(new_index, instance)
        self._reindex_layers(ordered)
