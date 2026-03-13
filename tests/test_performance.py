from __future__ import annotations

import json
from pathlib import Path

from sb3vm.cli import build_parser, cmd_benchmark
from sb3vm.io.load_sb3 import load_sb3
from sb3vm.model.project import Project
from sb3vm.vm.input_provider import HeadlessInputProvider
from sb3vm.vm.benchmark import run_benchmark_case
from sb3vm.vm.runtime import Sb3Vm


def _project(blocks_stage: dict) -> Project:
    return Project.from_json(
        {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {"v1": ["score", 0], "v2": ["done", 0]},
                    "lists": {"l1": ["items", []]},
                    "broadcasts": {"b1": "go"},
                    "blocks": blocks_stage,
                    "comments": {},
                    "costumes": [{"name": "backdrop1"}],
                    "sounds": [],
                }
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0"},
        }
    )


def test_inspect_reports_compile_capabilities() -> None:
    project = _project(
        {
            "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
            "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        }
    )

    vm = Sb3Vm(project)
    inspect = vm.inspect()
    capability = next(iter(inspect["script_capabilities"].values()))

    assert capability["compile_safe"] is True
    assert capability["compiled"] is False
    assert capability["runs"] == 0


def test_compiled_and_interpreted_runs_are_equivalent_for_safe_script() -> None:
    project = _project(
        {
            "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
            "set": {"opcode": "data_setvariableto", "next": "repeat", "parent": "hat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
            "repeat": {"opcode": "control_repeat", "next": "wait", "parent": "set", "inputs": {"TIMES": [1, [4, "3"]], "SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
            "chg": {"opcode": "data_changevariableby", "next": None, "parent": "repeat", "inputs": {"VALUE": [1, [4, "2"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
            "wait": {"opcode": "control_wait", "next": "done", "parent": "repeat", "inputs": {"DURATION": [1, [4, "0.05"]]}, "fields": {}, "topLevel": False},
            "done": {"opcode": "data_setvariableto", "next": None, "parent": "wait", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
        }
    )

    interpreted = Sb3Vm(project, enable_compilation=False)
    compiled = Sb3Vm(project, enable_compilation=True)

    interpreted.run_for(0.4)
    compiled.run_for(0.4)

    assert interpreted.snapshot()["stage_variables"] == compiled.snapshot()["stage_variables"]
    assert interpreted.snapshot()["targets"] == compiled.snapshot()["targets"]
    assert compiled.inspect()["script_capabilities"][next(iter(compiled.inspect()["script_capabilities"]))]["compiled"] is True


def test_lazy_hot_promotion_compiles_after_threshold() -> None:
    project = _project(
        {
            "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
            "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        }
    )
    vm = Sb3Vm(project, enable_compilation=True, lazy_compile_threshold=2)
    script_key = next(iter(vm.ir_scripts))

    vm.start_green_flag()
    vm.step(1 / 30)
    assert script_key not in vm._compiled_scripts

    vm.start_green_flag()
    vm.step(1 / 30)
    assert script_key in vm._compiled_scripts


def test_benchmark_case_returns_timing_shape() -> None:
    project = _project(
        {
            "hat": {"opcode": "event_whenflagclicked", "next": "repeat", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
            "repeat": {"opcode": "control_repeat", "next": None, "parent": "hat", "inputs": {"TIMES": [1, [4, "30"]], "SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
            "chg": {"opcode": "data_changevariableby", "next": None, "parent": "repeat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        }
    )

    result = run_benchmark_case("counter", project, seconds=0.2)

    assert result.name == "counter"
    assert result.iterations >= 1
    assert result.interpreted_seconds >= 0.0
    assert result.compiled_seconds >= 0.0
    assert result.to_dict()["name"] == "counter"


def test_compiled_broadcast_equivalence_for_safe_scripts() -> None:
    project = Project.from_json(
        {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {"v1": ["score", 0], "v2": ["done", 0]},
                    "lists": {},
                    "broadcasts": {"b1": "go"},
                    "blocks": {
                        "hat": {"opcode": "event_whenflagclicked", "next": "cast", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                        "cast": {"opcode": "event_broadcastandwait", "next": "done", "parent": "hat", "inputs": {"BROADCAST_INPUT": [1, [10, "go"]]}, "fields": {}, "topLevel": False},
                        "done": {"opcode": "data_setvariableto", "next": None, "parent": "cast", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
                    },
                    "comments": {},
                    "costumes": [{"name": "backdrop1"}],
                    "sounds": [],
                },
                {
                    "isStage": False,
                    "name": "Sprite1",
                    "variables": {},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {
                        "hat2": {"opcode": "event_whenbroadcastreceived", "next": "wait", "parent": None, "inputs": {}, "fields": {"BROADCAST_OPTION": ["go", "b1"]}, "topLevel": True},
                        "wait": {"opcode": "control_wait", "next": "add", "parent": "hat2", "inputs": {"DURATION": [1, [4, "0.1"]]}, "fields": {}, "topLevel": False},
                        "add": {"opcode": "data_changevariableby", "next": None, "parent": "wait", "inputs": {"VALUE": [1, [4, "5"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                    },
                    "comments": {},
                    "costumes": [{"name": "one"}],
                    "sounds": [],
                    "x": 0,
                    "y": 0,
                    "visible": True,
                    "currentCostume": 0,
                },
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0"},
        }
    )

    interpreted = Sb3Vm(project, enable_compilation=False)
    compiled = Sb3Vm(project, enable_compilation=True)

    interpreted.run_for(0.5)
    compiled.run_for(0.5)

    assert interpreted.snapshot()["stage_variables"] == compiled.snapshot()["stage_variables"]
    assert compiled.inspect()["script_capabilities"][next(iter(compiled.inspect()["script_capabilities"]))]["compiled"] is True


def test_compiled_sensing_equivalence_for_safe_scripts() -> None:
    project = _project(
        {
            "hat": {"opcode": "event_whenflagclicked", "next": "set_key", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
            "set_key": {"opcode": "data_setvariableto", "next": "set_mouse", "parent": "hat", "inputs": {"VALUE": [3, "key_expr"]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
            "key_expr": {"opcode": "sensing_keypressed", "next": None, "parent": "set_key", "inputs": {"KEY_OPTION": [1, "key_menu"]}, "fields": {}, "topLevel": False},
            "key_menu": {"opcode": "sensing_keyoptions", "next": None, "parent": "key_expr", "inputs": {}, "fields": {"KEY_OPTION": ["space", None]}, "topLevel": False},
            "set_mouse": {"opcode": "data_setvariableto", "next": None, "parent": "set_key", "inputs": {"VALUE": [3, "mouse_expr"]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
            "mouse_expr": {"opcode": "sensing_mousex", "next": None, "parent": "set_mouse", "inputs": {}, "fields": {}, "topLevel": False},
        }
    )
    provider = HeadlessInputProvider(pressed_keys={"space"}, mouse_x_value=17.0)

    interpreted = Sb3Vm(project, enable_compilation=False, input_provider=provider)
    compiled = Sb3Vm(project, enable_compilation=True, input_provider=HeadlessInputProvider(pressed_keys={"space"}, mouse_x_value=17.0))

    interpreted.run_for(0.2)
    compiled.run_for(0.2)

    assert interpreted.snapshot()["stage_variables"] == compiled.snapshot()["stage_variables"]


def test_compiled_ask_equivalence_for_safe_scripts() -> None:
    project = _project(
        {
            "hat": {"opcode": "event_whenflagclicked", "next": "ask", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
            "ask": {"opcode": "sensing_askandwait", "next": "store", "parent": "hat", "inputs": {"QUESTION": [1, [10, "name?"]]}, "fields": {}, "topLevel": False},
            "store": {"opcode": "data_setvariableto", "next": "done", "parent": "ask", "inputs": {"VALUE": [3, "answer_value"]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
            "answer_value": {"opcode": "sensing_answer", "next": None, "parent": "store", "inputs": {}, "fields": {}, "topLevel": False},
            "done": {"opcode": "data_setvariableto", "next": None, "parent": "store", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
        }
    )

    interpreted_provider = HeadlessInputProvider()
    compiled_provider = HeadlessInputProvider()
    interpreted = Sb3Vm(project, enable_compilation=False, input_provider=interpreted_provider)
    compiled = Sb3Vm(project, enable_compilation=True, input_provider=compiled_provider)

    interpreted.start_green_flag()
    compiled.start_green_flag()
    interpreted.step(1 / 30)
    compiled.step(1 / 30)

    assert interpreted.snapshot()["thread_frames"]["1"]["waiting_for_answer"] == "name?"
    assert compiled.snapshot()["thread_frames"]["1"]["waiting_for_answer"] == "name?"

    interpreted_provider.answers.append("Ada")
    compiled_provider.answers.append("Ada")
    interpreted.step(1 / 30)
    compiled.step(1 / 30)

    assert interpreted.snapshot()["stage_variables"] == compiled.snapshot()["stage_variables"]
    assert compiled.snapshot()["input_state"]["answer"] == "Ada"


def test_benchmark_cli_outputs_json(tmp_path, capsys) -> None:
    path = tmp_path / "bench.sb3"
    project = {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {"v1": ["score", 0]},
                "lists": {},
                "broadcasts": {},
                "blocks": {
                    "hat": {"opcode": "event_whenflagclicked", "next": "repeat", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                    "repeat": {"opcode": "control_repeat", "next": None, "parent": "hat", "inputs": {"TIMES": [1, [4, "5"]], "SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
                    "chg": {"opcode": "data_changevariableby", "next": None, "parent": "repeat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                },
                "comments": {},
                "costumes": [],
                "sounds": [],
            }
        ],
        "monitors": [],
        "extensions": [],
        "meta": {"semver": "3.0.0"},
    }
    from tests.test_helpers import write_sb3

    write_sb3(path, project)
    parser = build_parser()
    args = parser.parse_args(["benchmark", str(path), "--seconds", "0.1", "--name", "bench"])

    assert cmd_benchmark(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "bench"
    assert payload["iterations"] >= 1
    assert payload["interpreted_seconds"] >= 0.0
    assert payload["compiled_seconds"] >= 0.0


def test_benchmark_example_fixtures_exist_and_run() -> None:
    for name in ("benchmark_hot_loop", "benchmark_broadcast_fanout"):
        path = Path("examples") / f"{name}.sb3"
        project = load_sb3(path)
        result = run_benchmark_case(name, project, seconds=0.1)

        assert path.exists()
        assert result.name == name
        assert result.iterations >= 1
        assert result.interpreted_seconds >= 0.0
        assert result.compiled_seconds >= 0.0
