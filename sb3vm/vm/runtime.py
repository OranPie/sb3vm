from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, replace
from typing import Any

from sb3vm.log import debug, get_logger, info, trace, warn
from sb3vm.model.project import Project
from sb3vm.parse.ast_nodes import AskState, RuntimeDiagnostic, Script, Stmt
from sb3vm.parse.extract_scripts import extract_scripts
from sb3vm.parse.pretty import summarize_stmt
from sb3vm.vm.compiler import CompiledScript, compile_script
from sb3vm.vm.eval_expr import eval_expr
from sb3vm.vm.input_provider import HeadlessInputProvider, InputProvider, VmRng, normalize_key_name
from sb3vm.vm.ir import IrScript, lower_script
from sb3vm.vm.scratch_values import compare_equal, compare_order, letter_of, resolve_insert_index, resolve_list_index, to_bool, to_number
from sb3vm.vm.state import FrameState, LoopState, ThreadState, VMState


_LOGGER = get_logger(__name__)


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
        self._green_flag_scripts: tuple[Script, ...] = ()
        self._broadcast_scripts: dict[str, tuple[Script, ...]] = {}
        self._backdrop_scripts: dict[str, tuple[Script, ...]] = {}
        self._clone_start_scripts: dict[str, tuple[Script, ...]] = {}
        self._key_scripts: dict[str, tuple[Script, ...]] = {}
        self._any_key_scripts: tuple[Script, ...] = ()
        self._sprite_clicked_scripts: dict[str, tuple[Script, ...]] = {}
        self._greater_than_scripts: list[Script] = []
        self._greater_than_last_above: dict[int, bool] = {}
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
        self._next_dialogue_token = 1
        self._last_pressed_keys: set[str] = set()
        self._pending_instance_deletions: set[int] = set()
        self._costume_size_cache: dict[tuple[str, int], tuple[float, float]] = {}
        self._index_scripts()
        info(
            _LOGGER,
            "vm.Sb3Vm.__init__",
            "initialized vm targets=%d scripts=%d procedures=%d compiled=%s lazy_threshold=%s",
            len(self.project.targets),
            len(self.scripts),
            len(self.procedures),
            self.config.enable_compilation,
            self.config.lazy_compile_threshold,
        )

    def _index_scripts(self) -> None:
        green_flag_scripts: list[Script] = []
        broadcast_scripts: dict[str, list[Script]] = {}
        backdrop_scripts: dict[str, list[Script]] = {}
        clone_start_scripts: dict[str, list[Script]] = {}
        key_scripts: dict[str, list[Script]] = {}
        any_key_scripts: list[Script] = []
        sprite_clicked_scripts: dict[str, list[Script]] = {}
        for script in self.scripts:
            trigger = script.trigger
            if trigger.kind == "green_flag":
                green_flag_scripts.append(script)
                continue
            if trigger.kind == "broadcast_received":
                broadcast_scripts.setdefault(trigger.value or "", []).append(script)
                continue
            if trigger.kind == "backdrop_switched":
                backdrop_scripts.setdefault(trigger.value or "", []).append(script)
                continue
            if trigger.kind == "clone_start":
                clone_start_scripts.setdefault(script.target_name, []).append(script)
                continue
            if trigger.kind == "key_pressed":
                normalized = normalize_key_name(trigger.value or "")
                if normalized == "any":
                    any_key_scripts.append(script)
                else:
                    key_scripts.setdefault(normalized, []).append(script)
                continue
            if trigger.kind == "sprite_clicked":
                sprite_clicked_scripts.setdefault(script.target_name, []).append(script)
                continue
            if trigger.kind == "greater_than":
                if script.supported:
                    self._greater_than_scripts.append(script)
        self._green_flag_scripts = tuple(green_flag_scripts)
        self._broadcast_scripts = {name: tuple(scripts) for name, scripts in broadcast_scripts.items()}
        self._backdrop_scripts = {name: tuple(scripts) for name, scripts in backdrop_scripts.items()}
        self._clone_start_scripts = {name: tuple(scripts) for name, scripts in clone_start_scripts.items()}
        self._key_scripts = {name: tuple(scripts) for name, scripts in key_scripts.items()}
        self._any_key_scripts = tuple(any_key_scripts)
        self._sprite_clicked_scripts = {name: tuple(scripts) for name, scripts in sprite_clicked_scripts.items()}
        debug(
            _LOGGER,
            "vm.Sb3Vm._index_scripts",
            "indexed green=%d broadcasts=%d backdrops=%d clone_targets=%d key_bindings=%d any_key=%d sprite_click_targets=%d",
            len(self._green_flag_scripts),
            len(self._broadcast_scripts),
            len(self._backdrop_scripts),
            len(self._clone_start_scripts),
            len(self._key_scripts),
            len(self._any_key_scripts),
            len(self._sprite_clicked_scripts),
        )

    def timer_seconds(self) -> float:
        return self.state.timer_seconds(self.input_provider.timer_override(self.state.time_seconds))

    def random_index(self, length: int) -> int:
        return self.rng.randrange(length)

    def snapshot(self) -> dict[str, Any]:
        provider_state = self.input_provider.snapshot()
        provider_state["timer_seconds"] = self.timer_seconds()
        snapshot = self.state.snapshot(input_state=provider_state, random_seed=self.config.random_seed)
        thread_status = self.thread_statuses()
        snapshot["thread_status"] = thread_status
        for item in thread_status:
            thread_id = str(item["thread_id"])
            if thread_id in snapshot["thread_frames"]:
                snapshot["thread_frames"][thread_id]["current_statement"] = item["current_statement"]
                snapshot["thread_frames"][thread_id]["wait_state"] = item["wait_state"]
                snapshot["thread_frames"][thread_id]["wait_detail"] = item["wait_detail"]
        return snapshot

    def thread_statuses(self) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for thread in sorted(self.state.threads.values(), key=lambda item: item.spawn_order):
            if thread.done:
                continue
            instance = self.state.instances.get(thread.instance_id)
            statuses.append(
                {
                    "thread_id": thread.id,
                    "instance_id": thread.instance_id,
                    "target_name": instance.source_target_name if instance is not None else thread.root_target_name,
                    "root_trigger": thread.root_trigger,
                    "engine": thread.engine,
                    "frame_kind": thread.frames[-1].kind if thread.frames else None,
                    "call_depth": thread.call_depth(),
                    "current_statement": self._thread_current_statement(thread),
                    "wait_state": self._thread_wait_state(thread),
                    "wait_detail": self._thread_wait_detail(thread),
                }
            )
        return statuses

    def _thread_current_statement(self, thread: ThreadState) -> str | None:
        if thread.compiled_runner is not None:
            return "<compiled>"
        if self._thread_wait_state(thread) is not None and thread.current_stmt is not None:
            return summarize_stmt(thread.current_stmt)
        for frame in reversed(thread.frames):
            if frame.index < len(frame.stmts):
                stmt = frame.stmts[frame.index]
                return summarize_stmt(stmt)
        if thread.current_stmt is not None:
            return summarize_stmt(thread.current_stmt)
        return None

    def _thread_wait_state(self, thread: ThreadState) -> str | None:
        if thread.waiting_for_answer is not None:
            return "answer"
        if thread.waiting_for_children:
            return "children"
        if thread.glide is not None:
            return "glide"
        if thread.wake_time > self.state.time_seconds:
            return "sleep"
        return None

    def _thread_wait_detail(self, thread: ThreadState) -> str | None:
        if thread.waiting_for_answer is not None:
            return thread.waiting_for_answer.prompt
        if thread.waiting_for_children:
            return thread.wait_reason
        if thread.glide is not None:
            return f"until {thread.glide['to_x']:.1f},{thread.glide['to_y']:.1f}"
        if thread.wake_time > self.state.time_seconds:
            return f"until {thread.wake_time:.3f}s"
        return None

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
        info(_LOGGER, "vm.Sb3Vm.run_for", "running for %.3fs dt=%.5f", seconds, dt)
        self.start_green_flag()
        steps = max(0, int(seconds / dt))
        for _ in range(steps):
            self.step(dt)
        info(_LOGGER, "vm.Sb3Vm.run_for", "run finished time=%.3f remaining_threads=%d", self.state.time_seconds, len(self.state.threads))
        return RunResult(self.state, self.scripts)

    def start_green_flag(self) -> None:
        info(_LOGGER, "vm.Sb3Vm.start_green_flag", "starting %d green-flag scripts", len(self._green_flag_scripts))
        for script in self._green_flag_scripts:
            if not script.supported:
                warn(_LOGGER, "vm.Sb3Vm.start_green_flag", "skipping unsupported green-flag script target=%s", script.target_name)
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            self._spawn_for_matching_instances(script, include_clones=False)

    def emit_broadcast(self, name: str, wait_parent: ThreadState | None = None) -> set[int]:
        info(_LOGGER, "vm.Sb3Vm.emit_broadcast", "broadcast=%s wait=%s", name, wait_parent is not None)
        child_ids: set[int] = set()
        for script in self._broadcast_scripts.get(name, ()):
            if not script.supported:
                warn(_LOGGER, "vm.Sb3Vm.emit_broadcast", "skipping unsupported broadcast script target=%s name=%s", script.target_name, name)
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids |= self._spawn_for_matching_instances(script, include_clones=True)
        if wait_parent is not None:
            wait_parent.waiting_for_children |= child_ids
            wait_parent.wait_reason = f"broadcast:{name}"
        debug(_LOGGER, "vm.Sb3Vm.emit_broadcast", "broadcast=%s spawned_children=%d", name, len(child_ids))
        return child_ids

    def emit_key_press(self, key_name: str) -> set[int]:
        normalized_key = normalize_key_name(key_name)
        child_ids: set[int] = set()
        for script in self._key_scripts.get(normalized_key, ()):
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids |= self._spawn_for_matching_instances(script, include_clones=True)
        for script in self._any_key_scripts:
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids |= self._spawn_for_matching_instances(script, include_clones=True)
        return child_ids

    def emit_backdrop_switch(self, name: str, wait_parent: ThreadState | None = None) -> set[int]:
        child_ids: set[int] = set()
        for script in self._backdrop_scripts.get(name, ()):
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids |= self._spawn_for_matching_instances(script, include_clones=True)
        if wait_parent is not None:
            wait_parent.waiting_for_children |= child_ids
            wait_parent.wait_reason = f"backdrop:{name}"
        return child_ids

    def emit_sprite_click(self, instance_id: int) -> set[int]:
        instance = self.state.instances.get(instance_id)
        if instance is None or instance.is_stage:
            return set()
        child_ids: set[int] = set()
        for script in self._sprite_clicked_scripts.get(instance.source_target_name, ()):
            if not script.supported:
                self.state.unsupported_scripts.extend(script.unsupported_details)
                continue
            child_ids.add(self._spawn_script(script, instance_id).id)
        return child_ids

    def _spawn_clone_start(self, instance_id: int) -> set[int]:
        child_ids: set[int] = set()
        source_target_name = self.state.get_instance(instance_id).source_target_name
        for script in self._clone_start_scripts.get(source_target_name, ()):
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
        debug(
            _LOGGER,
            "vm.Sb3Vm._spawn_script",
            "spawned thread id=%d instance=%d target=%s trigger=%s engine=%s",
            tid,
            instance_id,
            script.target_name,
            script.trigger.kind,
            thread.engine,
        )
        return thread

    def step(self, dt: float) -> None:
        trace(_LOGGER, "vm.Sb3Vm.step", "step begin dt=%.5f time=%.5f threads=%d", dt, self.state.time_seconds, len(self.state.threads))
        self.state.time_seconds += dt
        self._poll_input_events()
        self._poll_greater_than_triggers()
        threads = self.state.threads
        for thread in tuple(threads.values()):
            if thread.done:
                continue
            if thread.instance_id in self._pending_instance_deletions:
                thread.done = True
                continue
            self._clear_dialogue_if_ready(thread)
            if thread.waiting_for_answer is not None:
                answer = self.input_provider.pop_answer()
                if answer is None:
                    continue
                self.input_provider.set_answer(answer)
                thread.waiting_for_answer = None
            if thread.waiting_for_children:
                alive = {tid for tid in thread.waiting_for_children if tid in threads and not threads[tid].done}
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
        for tid in [tid for tid, thread in threads.items() if thread.done]:
            threads.pop(tid, None)
        for instance_id in list(self._pending_instance_deletions):
            self.state.instances.pop(instance_id, None)
            self._pending_instance_deletions.discard(instance_id)
        trace(_LOGGER, "vm.Sb3Vm.step", "step end time=%.5f threads=%d", self.state.time_seconds, len(self.state.threads))

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
            if frame.kind == "wait_until_loop":
                if frame.loop is None:
                    thread.frames.pop()
                    continue
                if to_bool(eval_expr(frame.loop.condition, self.state, thread, self)):
                    thread.frames.pop()
                    continue
                return
            if frame.index >= len(frame.stmts):
                popped = thread.frames.pop()
                if popped.kind == "sequence" and thread.frames and thread.frames[-1].kind in {"repeat_loop", "repeat_until_loop", "forever_loop"}:
                    if not thread.in_warp():
                        return
                continue

            stmt = frame.stmts[frame.index]
            frame.index += 1
            thread.current_stmt = stmt
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
        thread.current_stmt = None
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
        if kind == "music_play_note":
            eval_expr(stmt.args["note"], self.state, thread, self)
            thread.wake_time = self.state.time_seconds + self._beats_to_seconds(eval_expr(stmt.args["beats"], self.state, thread, self))
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
        if kind == "no_op":
            return None
        if kind == "wait_until":
            thread.frames.append(FrameState(kind="wait_until_loop", stmts=[], loop=LoopState(kind="wait_until", body=[], condition=stmt.args["condition"])))
            return "yield"
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
            warn(_LOGGER, "vm.Sb3Vm._call_procedure", "missing procedure target=%s proccode=%s", source_target_name, proccode)
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
            warn(_LOGGER, "vm.Sb3Vm._call_procedure", "recursion limit hit target=%s proccode=%s depth=%d", source_target_name, proccode, thread.call_depth() + 1)
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
        for arg_id, arg_name, default in zip(procedure.argument_ids, procedure.argument_names, procedure.argument_defaults):
            bound_arguments.setdefault(arg_id, default)
            bound_arguments.setdefault(arg_name, bound_arguments[arg_id])
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
        token = str(selector).strip()
        if token.lower() in {"myself", "_myself_"}:
            base_instance = source_instance
        else:
            if token not in self.state.original_instance_ids:
                warn(_LOGGER, "vm.Sb3Vm._create_clone", "invalid clone target=%s source=%s", token, source_instance.source_target_name)
                self.state.runtime_diagnostics.append(
                    RuntimeDiagnostic(
                        kind="invalid_clone_target",
                        message=f"Unknown clone target: {token}",
                        target_name=source_instance.source_target_name,
                        thread_id=thread.id,
                        instance_id=thread.instance_id,
                    )
                )
                return
            base_instance = self.state.get_instance(self.state.get_original_instance_id(token))
        if base_instance.is_stage:
            warn(_LOGGER, "vm.Sb3Vm._create_clone", "attempted to clone stage target=%s", token or base_instance.source_target_name)
            self.state.runtime_diagnostics.append(
                RuntimeDiagnostic(
                    kind="invalid_clone_target",
                    message=f"Cannot clone target: {token or base_instance.source_target_name}",
                    target_name=source_instance.source_target_name,
                    thread_id=thread.id,
                    instance_id=thread.instance_id,
                )
            )
            return
        if self.state.live_clone_count() >= self.config.max_clones:
            warn(_LOGGER, "vm.Sb3Vm._create_clone", "clone limit reached target=%s limit=%d", base_instance.source_target_name, self.config.max_clones)
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
        info(_LOGGER, "vm.Sb3Vm._create_clone", "created clone instance=%d source=%s", new_instance.instance_id, new_instance.source_target_name)

    def _delete_clone(self, thread: ThreadState) -> str:
        instance = self.state.get_instance(thread.instance_id)
        if not instance.is_clone:
            warn(_LOGGER, "vm.Sb3Vm._delete_clone", "delete_this_clone called on non-clone target=%s", instance.source_target_name)
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

    def _stage_tempo(self) -> float:
        try:
            tempo = float(self.project.get_target("Stage").tempo)
        except (KeyError, TypeError, ValueError):
            return 60.0
        return tempo if tempo > 0 else 60.0

    def _beats_to_seconds(self, beats: Any) -> float:
        return max(0.0, to_number(beats)) * 60.0 / self._stage_tempo()

    def touching_object(self, instance_id: int, selector: Any) -> bool:
        instance = self.state.get_instance(instance_id)
        if instance.is_stage:
            return False
        bounds = self._instance_bounds(instance)
        if bounds is None:
            return False
        token = str(selector).strip()
        lowered = token.lower()
        if lowered == "_mouse_":
            return self._bounds_contains_point(bounds, self.input_provider.mouse_x(), self.input_provider.mouse_y())
        if lowered == "_edge_":
            left, bottom, right, top = bounds
            return left <= -240.0 or right >= 240.0 or bottom <= -180.0 or top >= 180.0
        for other in self.state.instances.values():
            if other.instance_id == instance.instance_id or other.source_target_name != token:
                continue
            other_bounds = self._instance_bounds(other)
            if other_bounds is not None and self._bounds_overlap(bounds, other_bounds):
                return True
        return False

    def _instance_bounds(self, instance: Any) -> tuple[float, float, float, float] | None:
        if not instance.visible and not instance.is_stage:
            return None
        width, height = self._costume_dimensions(instance.source_target_name, instance.costume_index)
        if width <= 0 or height <= 0:
            return None
        half_width = width * max(0.0, instance.size) / 200.0
        half_height = height * max(0.0, instance.size) / 200.0
        return (instance.x - half_width, instance.y - half_height, instance.x + half_width, instance.y + half_height)

    def _costume_dimensions(self, target_name: str, costume_index: int) -> tuple[float, float]:
        costumes = self._target_costumes(target_name)
        if not costumes:
            return (0.0, 0.0)
        resolved_index = costume_index % len(costumes)
        cache_key = (target_name, resolved_index)
        cached = self._costume_size_cache.get(cache_key)
        if cached is not None:
            return cached
        dims = self._read_costume_dimensions(costumes[resolved_index])
        self._costume_size_cache[cache_key] = dims
        return dims

    def _read_costume_dimensions(self, costume: dict[str, Any]) -> tuple[float, float]:
        asset_name = str(costume.get("md5ext") or "")
        if not asset_name:
            asset_id = costume.get("assetId")
            data_format = costume.get("dataFormat")
            if asset_id and data_format:
                asset_name = f"{asset_id}.{data_format}"
        payload = self.project.assets.get(asset_name) if asset_name else None
        if payload:
            suffix = asset_name.rsplit(".", 1)[-1].lower() if "." in asset_name else str(costume.get("dataFormat", "")).lower()
            if suffix == "svg":
                dims = self._parse_svg_dimensions(payload)
                if dims is not None:
                    return dims
            if suffix == "png":
                dims = self._parse_png_dimensions(payload)
                if dims is not None:
                    return dims
        fallback_width = max(0.0, float(costume.get("rotationCenterX", 0.0)) * 2.0)
        fallback_height = max(0.0, float(costume.get("rotationCenterY", 0.0)) * 2.0)
        return (fallback_width, fallback_height)

    def _parse_svg_dimensions(self, payload: bytes) -> tuple[float, float] | None:
        text = payload.decode("utf-8", errors="ignore")
        width = self._parse_svg_length(self._match_svg_attr(text, "width"))
        height = self._parse_svg_length(self._match_svg_attr(text, "height"))
        if width > 0 and height > 0:
            return (width, height)
        view_box = self._match_svg_attr(text, "viewBox")
        if view_box:
            numbers = [self._parse_svg_length(part) for part in re.split(r"[\s,]+", view_box.strip()) if part]
            if len(numbers) == 4 and numbers[2] > 0 and numbers[3] > 0:
                return (numbers[2], numbers[3])
        return None

    def _match_svg_attr(self, text: str, name: str) -> str | None:
        match = re.search(rf'\b{name}\s*=\s*["\']([^"\']+)["\']', text)
        if match is None:
            return None
        return match.group(1)

    def _parse_svg_length(self, raw: str | None) -> float:
        if not raw:
            return 0.0
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", raw)
        if match is None:
            return 0.0
        return abs(float(match.group(0)))

    def _parse_png_dimensions(self, payload: bytes) -> tuple[float, float] | None:
        if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
            return None
        width, height = struct.unpack(">II", payload[16:24])
        return (float(width), float(height))

    def _bounds_contains_point(self, bounds: tuple[float, float, float, float], x: float, y: float) -> bool:
        left, bottom, right, top = bounds
        return left <= x <= right and bottom <= y <= top

    def _bounds_overlap(
        self,
        first: tuple[float, float, float, float],
        second: tuple[float, float, float, float],
    ) -> bool:
        left_a, bottom_a, right_a, top_a = first
        left_b, bottom_b, right_b, top_b = second
        return left_a <= right_b and right_a >= left_b and bottom_a <= top_b and top_a >= bottom_b

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
        elif mode == "move_steps":
            steps = to_number(values["steps"])
            angle = math.radians(instance.direction - 90.0)
            instance.x += steps * math.cos(angle)
            instance.y += steps * math.sin(angle)
        elif mode == "if_edge_bounce":
            self._apply_if_edge_bounce(instance)
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
        elif mode == "dialogue":
            message = str(values["message"])
            duration = values.get("duration")
            if duration is None:
                self._set_dialogue(instance, str(values["style"]), message)
            else:
                token = self._set_dialogue(instance, str(values["style"]), message)
                thread.dialogue_clear_instance_id = instance.instance_id
                thread.dialogue_clear_token = token
                thread.wake_time = self.state.time_seconds + max(0.0, to_number(duration))
                return "block"
        elif mode == "switch_backdrop":
            child_ids = self._switch_backdrop(values["backdrop"], wait_parent=thread if values.get("wait") else None)
            if values.get("wait") and child_ids:
                return "block"
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

    def _set_dialogue(self, instance: Any, style: str, message: str) -> int:
        token = self._next_dialogue_token
        self._next_dialogue_token += 1
        instance.dialogue = {"style": style, "text": message}
        instance.dialogue_token = token
        return token

    def _clear_dialogue_if_ready(self, thread: ThreadState) -> None:
        if thread.dialogue_clear_token is None or thread.dialogue_clear_instance_id is None:
            return
        if thread.wake_time > self.state.time_seconds:
            return
        instance = self.state.instances.get(thread.dialogue_clear_instance_id)
        if instance is not None and instance.dialogue_token == thread.dialogue_clear_token:
            instance.dialogue = None
        thread.dialogue_clear_instance_id = None
        thread.dialogue_clear_token = None

    def _backdrop_name(self) -> str:
        stage = self._stage_instance()
        costumes = self._target_costumes(stage.source_target_name)
        if not costumes:
            return ""
        return str(costumes[stage.costume_index % len(costumes)].get("name", ""))

    def _switch_backdrop(self, value: Any, wait_parent: ThreadState | None = None) -> set[int]:
        stage = self._stage_instance()
        index = self._resolve_costume_index(stage.source_target_name, value)
        if index is None:
            return set()
        if stage.costume_index == index:
            return set()
        stage.costume_index = index
        return self.emit_backdrop_switch(self._backdrop_name(), wait_parent=wait_parent)

    def _advance_backdrop(self, delta: int, wait_parent: ThreadState | None = None) -> set[int]:
        stage = self._stage_instance()
        costumes = self._target_costumes(stage.source_target_name)
        if not costumes:
            return set()
        next_index = (stage.costume_index + delta) % len(costumes)
        if next_index == stage.costume_index:
            return set()
        stage.costume_index = next_index
        return self.emit_backdrop_switch(self._backdrop_name(), wait_parent=wait_parent)

    def _poll_input_events(self) -> None:
        current_keys = {normalize_key_name(key) for key in self.input_provider.active_keys()}
        new_keys = sorted(current_keys - self._last_pressed_keys)
        for key_name in new_keys:
            self.emit_key_press(key_name)
        self._last_pressed_keys = current_keys

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

    def _poll_greater_than_triggers(self) -> None:
        for index, script in enumerate(self._greater_than_scripts):
            trigger = script.trigger
            menu = (trigger.value or "").upper()
            if menu == "TIMER":
                current_val = self.timer_seconds()
            else:
                current_val = 0.0
            # Evaluate threshold using a temporary thread on the stage
            stage_id = self.state.original_instance_ids.get("Stage", next(iter(self.state.original_instance_ids.values()), 0))
            dummy_thread = ThreadState(id=0, instance_id=stage_id)
            threshold_val = to_number(eval_expr(trigger.threshold, self.state, dummy_thread, self)) if trigger.threshold is not None else 0.0
            was_above = self._greater_than_last_above.get(index, False)
            now_above = current_val > threshold_val
            self._greater_than_last_above[index] = now_above
            if now_above and not was_above:
                self._spawn_for_matching_instances(script, include_clones=False)

    def _sensing_of(self, instance_id: int, property_name: str, target_selector: Any) -> Any:
        token = str(target_selector).strip()
        lowered_token = token.lower()
        prop = property_name.strip().lower()
        # Resolve target instance
        if lowered_token in {"_stage_", "stage"}:
            target_inst = self.state.instances.get(self.state.original_instance_ids.get("Stage", -1))
        else:
            orig_id = self.state.original_instance_ids.get(token)
            target_inst = self.state.instances.get(orig_id) if orig_id is not None else None
        if target_inst is None:
            return 0
        if prop == "x position":
            return target_inst.x
        if prop == "y position":
            return target_inst.y
        if prop == "direction":
            return target_inst.direction
        if prop == "costume #" or prop == "costume number":
            return target_inst.costume_index + 1
        if prop == "costume name":
            costumes = self._target_costumes(target_inst.source_target_name)
            if not costumes:
                return ""
            return costumes[target_inst.costume_index % len(costumes)].get("name", "")
        if prop == "size":
            return target_inst.size
        if prop == "backdrop #" or prop == "backdrop number":
            stage = self._stage_instance()
            return stage.costume_index + 1
        if prop == "backdrop name":
            return self._backdrop_name()
        if prop == "volume":
            return 100
        # Fall back to variable lookup
        val = target_inst.local_variables.get(property_name)
        if val is not None:
            return val
        return self.state.stage_variables.get(property_name, 0)

    def _distance_to(self, instance_id: int, selector: Any) -> float:
        instance = self.state.get_instance(instance_id)
        token = str(selector).strip()
        lowered = token.lower()
        if lowered == "_mouse_":
            tx = self.input_provider.mouse_x()
            ty = self.input_provider.mouse_y()
        else:
            orig_id = self.state.original_instance_ids.get(token)
            if orig_id is None:
                return 10000.0
            other = self.state.instances.get(orig_id)
            if other is None:
                return 10000.0
            tx, ty = other.x, other.y
        dx = instance.x - tx
        dy = instance.y - ty
        return math.sqrt(dx * dx + dy * dy)

    def _apply_if_edge_bounce(self, instance: Any) -> None:
        half_w = 240.0
        half_h = 180.0
        x, y = instance.x, instance.y
        # Convert Scratch direction to math angle (radians)
        math_angle = math.radians(90.0 - instance.direction)
        vx = math.cos(math_angle)
        vy = math.sin(math_angle)
        bounced = False
        if x <= -half_w or x >= half_w:
            vx = -vx
            bounced = True
            x = max(-half_w, min(half_w, x))
        if y <= -half_h or y >= half_h:
            vy = -vy
            bounced = True
            y = max(-half_h, min(half_h, y))
        if bounced:
            instance.x = x
            instance.y = y
            new_math_angle = math.atan2(vy, vx)
            instance.direction = self._normalize_direction(90.0 - math.degrees(new_math_angle))
