from __future__ import annotations

import json
import subprocess
import sys

import pytest

from sb3vm.io.load_sb3 import load_sb3
from sb3vm.vm.errors import ProjectValidationError
from sb3vm.vm.input_provider import HeadlessInputProvider
from sb3vm.vm.runtime import Sb3Vm
from tests.test_helpers import fixture_project, write_sb3


def _base_project(blocks_stage=None, blocks_sprite=None):
    return {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {"v1": ["score", 0], "v2": ["done", 0]},
                "lists": {"l1": ["items", []]},
                "broadcasts": {"b1": "go"},
                "blocks": blocks_stage or {},
                "comments": {},
                "costumes": [],
                "sounds": [],
            },
            {
                "isStage": False,
                "name": "Sprite1",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": blocks_sprite or {},
                "comments": {},
                "costumes": [{"name": "one"}, {"name": "two"}],
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


def _procedure_definition(block_id, prototype_id, next_block, *, proccode, arg_ids, arg_names, defaults, warp=False):
    return {
        block_id: {
            "opcode": "procedures_definition",
            "next": next_block,
            "parent": None,
            "inputs": {"custom_block": [1, prototype_id]},
            "fields": {},
            "topLevel": True,
        },
        prototype_id: {
            "opcode": "procedures_prototype",
            "next": None,
            "parent": block_id,
            "inputs": {},
            "fields": {},
            "topLevel": False,
            "mutation": {
                "proccode": proccode,
                "argumentids": json.dumps(arg_ids),
                "argumentnames": json.dumps(arg_names),
                "argumentdefaults": json.dumps(defaults),
                "warp": "true" if warp else "false",
            },
        },
    }


def _procedure_call(block_id, *, proccode, arg_values, next_block=None, parent=None):
    return {
        block_id: {
            "opcode": "procedures_call",
            "next": next_block,
            "parent": parent,
            "inputs": arg_values,
            "fields": {},
            "topLevel": False,
            "mutation": {"proccode": proccode},
        }
    }


def _clone_menu(block_id, value, *, parent=None):
    return {
        block_id: {
            "opcode": "control_create_clone_of_menu",
            "next": None,
            "parent": parent,
            "inputs": {},
            "fields": {"CLONE_OPTION": [value, None]},
            "topLevel": False,
        }
    }


def _create_clone(block_id, selector, *, next_block=None, parent=None):
    if selector == "myself":
        return {
            block_id: {
                "opcode": "control_create_clone_of",
                "next": next_block,
                "parent": parent,
                "inputs": {},
                "fields": {"CLONE_OPTION": ["myself", None]},
                "topLevel": False,
            }
        }
    menu_id = f"{block_id}_menu"
    return {
        block_id: {
            "opcode": "control_create_clone_of",
            "next": next_block,
            "parent": parent,
            "inputs": {"CLONE_OPTION": [1, menu_id]},
            "fields": {},
            "topLevel": False,
        },
        **_clone_menu(menu_id, selector, parent=block_id),
    }


def _key_menu(block_id, value, *, parent=None):
    return {
        block_id: {
            "opcode": "sensing_keyoptions",
            "next": None,
            "parent": parent,
            "inputs": {},
            "fields": {"KEY_OPTION": [value, None]},
            "topLevel": False,
        }
    }


def test_green_flag_repeat_and_motion(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set": {"opcode": "data_setvariableto", "next": "repeat", "parent": "hat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        "repeat": {"opcode": "control_repeat", "next": "goto", "parent": "set", "inputs": {"TIMES": [1, [4, "3"]], "SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
        "chg": {"opcode": "data_changevariableby", "next": None, "parent": "repeat", "inputs": {"VALUE": [1, [4, "2"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        "goto": {"opcode": "motion_gotoxy", "next": "hide", "parent": "repeat", "inputs": {"X": [1, [4, "10"]], "Y": [1, [4, "-5"]]}, "fields": {}, "topLevel": False},
        "hide": {"opcode": "looks_hide", "next": None, "parent": "goto", "inputs": {}, "fields": {}, "topLevel": False},
    }
    path = tmp_path / "project.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))
    vm = Sb3Vm(load_sb3(path))
    result = vm.run_for(0.5)
    assert result.vm_state.stage_variables["score"] == 7.0
    assert result.vm_state.targets["Stage"].x == 10.0
    assert result.vm_state.targets["Stage"].y == -5.0
    assert result.vm_state.targets["Stage"].visible is False


def test_broadcast_and_wait(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "cast", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "cast": {"opcode": "event_broadcastandwait", "next": "done", "parent": "hat", "inputs": {"BROADCAST_INPUT": [1, [10, "go"]]}, "fields": {}, "topLevel": False},
        "done": {"opcode": "data_setvariableto", "next": None, "parent": "cast", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
    }
    sprite_blocks = {
        "hat2": {"opcode": "event_whenbroadcastreceived", "next": "wait", "parent": None, "inputs": {}, "fields": {"BROADCAST_OPTION": ["go", "b1"]}, "topLevel": True},
        "wait": {"opcode": "control_wait", "next": "add", "parent": "hat2", "inputs": {"DURATION": [1, [4, "0.1"]]}, "fields": {}, "topLevel": False},
        "add": {"opcode": "data_changevariableby", "next": None, "parent": "wait", "inputs": {"VALUE": [1, [4, "5"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
    }
    path = tmp_path / "project.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks, blocks_sprite=sprite_blocks))
    vm = Sb3Vm(load_sb3(path))
    result = vm.run_for(0.5)
    assert result.vm_state.stage_variables["score"] == 5.0
    assert result.vm_state.stage_variables["done"] == 1


def test_list_operations(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "add1", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "add1": {"opcode": "data_addtolist", "next": "add2", "parent": "hat", "inputs": {"ITEM": [1, [10, "a"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "add2": {"opcode": "data_addtolist", "next": "ins", "parent": "add1", "inputs": {"ITEM": [1, [10, "c"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "ins": {"opcode": "data_insertatlist", "next": "rep", "parent": "add2", "inputs": {"INDEX": [1, [4, "2"]], "ITEM": [1, [10, "b"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "rep": {"opcode": "data_replaceitemoflist", "next": None, "parent": "ins", "inputs": {"INDEX": [1, [4, "3"]], "ITEM": [1, [10, "z"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
    }
    path = tmp_path / "project.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))
    vm = Sb3Vm(load_sb3(path))
    result = vm.run_for(0.2)
    assert result.vm_state.stage_lists["items"] == ["a", "b", "z"]


def test_list_index_and_coercion_compatibility(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "add_one", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "add_one": {"opcode": "data_addtolist", "next": "insert_front", "parent": "hat", "inputs": {"ITEM": [1, [4, "1"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "insert_front": {"opcode": "data_insertatlist", "next": "insert_end", "parent": "add_one", "inputs": {"INDEX": [1, [4, "0"]], "ITEM": [1, [10, "front"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "insert_end": {"opcode": "data_insertatlist", "next": "replace_last", "parent": "insert_front", "inputs": {"INDEX": [1, [4, "999"]], "ITEM": [1, [10, "end"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "replace_last": {"opcode": "data_replaceitemoflist", "next": "store_missing", "parent": "insert_end", "inputs": {"INDEX": [1, [10, "last"]], "ITEM": [1, [10, "tail"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "store_missing": {"opcode": "data_setvariableto", "next": "store_compare", "parent": "replace_last", "inputs": {"VALUE": [3, "missing_item"]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        "missing_item": {"opcode": "data_itemoflist", "next": None, "parent": "store_missing", "inputs": {"INDEX": [1, [4, "10"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
        "store_compare": {"opcode": "data_setvariableto", "next": "store_contains", "parent": "store_missing", "inputs": {"VALUE": [3, "compare_expr"]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
        "compare_expr": {"opcode": "operator_equals", "next": None, "parent": "store_compare", "inputs": {"OPERAND1": [1, [10, "01"]], "OPERAND2": [1, [4, "1"]]}, "fields": {}, "topLevel": False},
        "store_contains": {"opcode": "data_setvariableto", "next": None, "parent": "store_compare", "inputs": {"VALUE": [3, "contains_expr"]}, "fields": {"VARIABLE": ["contains", "sv1"]}, "topLevel": False},
        "contains_expr": {"opcode": "data_listcontainsitem", "next": None, "parent": "store_contains", "inputs": {"ITEM": [1, [10, "1"]]}, "fields": {"LIST": ["items", "l1"]}, "topLevel": False},
    }
    project = _base_project(blocks_stage=blocks)
    project["targets"][0]["variables"]["sv1"] = ["contains", 0]
    path = tmp_path / "list_compat.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.4)

    assert vm.state.stage_lists["items"] == ["front", 1, "tail"]
    assert vm.state.stage_variables["score"] == ""
    assert vm.state.stage_variables["done"] is True
    assert vm.state.stage_variables["contains"] is True


def test_inspect_reports_structured_unsupported_diagnostics(tmp_path):
    path = tmp_path / "unsupported.sb3"
    write_sb3(path, fixture_project("unsupported_broadcast"))

    vm = Sb3Vm(load_sb3(path))
    inspect = vm.inspect()

    assert inspect["opcode_coverage"]["unsupported_by_opcode"] == {"looks_say": 1}
    assert inspect["unsupported_scripts"] == [
        {
            "target": "Stage",
            "trigger": "green_flag",
            "value": None,
            "node_kind": "statement",
            "opcode": "looks_say",
            "reason": "unsupported statement opcode",
            "block_id": "say",
        }
    ]


def test_run_uses_stable_snapshot_shape(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat", "inputs": {"VALUE": [1, [4, "9"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
    }
    path = tmp_path / "snapshot.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)
    snapshot = vm.snapshot()

    assert snapshot["stage_variables"] == {"done": 0, "score": 9}
    assert snapshot["targets"]["Stage"]["variables"]["score"] == 9
    assert snapshot["targets"]["Stage"]["is_stage"] is True
    assert snapshot["targets"]["Stage"]["is_clone"] is False
    assert snapshot["instances"]["1"]["source_target_name"] == "Stage"
    assert snapshot["clone_count"] == 0
    assert snapshot["active_threads"] == 0
    assert snapshot["unsupported_scripts"] == []


def test_missing_block_reference_fails_clearly(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "missing", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
    }
    path = tmp_path / "invalid.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    with pytest.raises(ProjectValidationError, match="Missing referenced block in script chain"):
        Sb3Vm(load_sb3(path))


def test_cli_reports_validation_error_on_invalid_project(tmp_path):
    path = tmp_path / "invalid_cli.sb3"
    write_sb3(
        path,
        {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {"hat": []},
                    "comments": {},
                    "costumes": [],
                    "sounds": [],
                }
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0"},
        },
    )

    proc = subprocess.run(
        [sys.executable, "-m", "sb3vm.cli", "inspect", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1
    assert "error: Block entry must be an object" in proc.stderr
    assert "block=hat" in proc.stderr


def test_cli_inspect_emits_opcode_coverage_json(tmp_path):
    path = tmp_path / "unsupported_cli.sb3"
    write_sb3(path, fixture_project("unsupported_broadcast"))

    proc = subprocess.run(
        [sys.executable, "-m", "sb3vm.cli", "inspect", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert payload["opcode_coverage"]["by_opcode"]["looks_say"] == 1
    assert payload["unsupported_scripts"][0]["opcode"] == "looks_say"


def test_custom_procedure_arguments_and_nested_calls(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "outer_call", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_procedure_call(
            "outer_call",
            proccode="outer %s",
            arg_values={"arg_outer": [1, [4, "5"]]},
            parent="hat",
        ),
        **_procedure_definition(
            "outer_def",
            "outer_proto",
            "inner_call",
            proccode="outer %s",
            arg_ids=["arg_outer"],
            arg_names=["amount"],
            defaults=[""],
        ),
        **_procedure_call(
            "inner_call",
            proccode="inner %s",
            arg_values={"arg_inner": [3, "outer_arg"]},
            parent="outer_def",
        ),
        "outer_arg": {
            "opcode": "argument_reporter_string_number",
            "next": None,
            "parent": "inner_call",
            "inputs": {},
            "fields": {"VALUE": ["amount", None]},
            "topLevel": False,
        },
        **_procedure_definition(
            "inner_def",
            "inner_proto",
            "chg",
            proccode="inner %s",
            arg_ids=["arg_inner"],
            arg_names=["value"],
            defaults=[""],
        ),
        "chg": {
            "opcode": "data_changevariableby",
            "next": None,
            "parent": "inner_def",
            "inputs": {"VALUE": [3, "inner_arg"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "inner_arg": {
            "opcode": "argument_reporter_string_number",
            "next": None,
            "parent": "chg",
            "inputs": {},
            "fields": {"VALUE": ["value", None]},
            "topLevel": False,
        },
    }
    path = tmp_path / "procedures.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path))
    inspect = vm.inspect()
    result = vm.run_for(0.3)

    assert [proc["proccode"] for proc in inspect["procedures"]] == ["inner %s", "outer %s"]
    assert result.vm_state.stage_variables["score"] == 5.0
    assert result.vm_state.runtime_diagnostics == []


def test_stop_inside_procedure_unwinds_owning_thread(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "call", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_procedure_call(
            "call",
            proccode="stopper",
            arg_values={},
            next_block="done",
            parent="hat",
        ),
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "call",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
        **_procedure_definition(
            "proc_def",
            "proc_proto",
            "set_score",
            proccode="stopper",
            arg_ids=[],
            arg_names=[],
            defaults=[],
        ),
        "set_score": {
            "opcode": "data_setvariableto",
            "next": "stopper_stmt",
            "parent": "proc_def",
            "inputs": {"VALUE": [1, [4, "7"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "stopper_stmt": {
            "opcode": "control_stop",
            "next": None,
            "parent": "set_score",
            "inputs": {},
            "fields": {"STOP_OPTION": ["this script", None]},
            "topLevel": False,
        },
    }
    path = tmp_path / "stopper.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.3)

    assert vm.state.stage_variables["score"] == 7
    assert vm.state.stage_variables["done"] == 0


def test_stop_other_scripts_in_sprite_terminates_siblings(tmp_path):
    sprite_blocks = {
        "hat_a": {"opcode": "event_whenflagclicked", "next": "wait_then_add", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "wait_then_add": {
            "opcode": "control_wait",
            "next": "add_one",
            "parent": "hat_a",
            "inputs": {"DURATION": [1, [4, "0.2"]]},
            "fields": {},
            "topLevel": False,
        },
        "add_one": {"opcode": "data_changevariableby", "next": None, "parent": "wait_then_add", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["hits", "sv1"]}, "topLevel": False},
        "hat_b": {"opcode": "event_whenflagclicked", "next": "stop_others", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "stop_others": {"opcode": "control_stop", "next": "set_ten", "parent": "hat_b", "inputs": {}, "fields": {"STOP_OPTION": ["other scripts in sprite", None]}, "topLevel": False},
        "set_ten": {"opcode": "data_setvariableto", "next": None, "parent": "stop_others", "inputs": {"VALUE": [1, [4, "10"]]}, "fields": {"VARIABLE": ["hits", "sv1"]}, "topLevel": False},
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["hits", 0]}
    path = tmp_path / "stop_other.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.4)

    assert vm.state.targets["Sprite1"].local_variables["hits"] == 10


def test_stop_all_halts_all_threads(tmp_path):
    blocks = {
        "hat1": {"opcode": "event_whenflagclicked", "next": "wait_stop", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "wait_stop": {"opcode": "control_wait", "next": "stop_all", "parent": "hat1", "inputs": {"DURATION": [1, [4, "0.05"]]}, "fields": {}, "topLevel": False},
        "stop_all": {"opcode": "control_stop", "next": None, "parent": "wait_stop", "inputs": {}, "fields": {"STOP_OPTION": ["all", None]}, "topLevel": False},
        "hat2": {"opcode": "event_whenflagclicked", "next": "delayed_add", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "delayed_add": {"opcode": "control_wait", "next": "add", "parent": "hat2", "inputs": {"DURATION": [1, [4, "0.2"]]}, "fields": {}, "topLevel": False},
        "add": {"opcode": "data_changevariableby", "next": None, "parent": "delayed_add", "inputs": {"VALUE": [1, [4, "5"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
    }
    path = tmp_path / "stop_all.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.4)

    assert vm.state.stage_variables["score"] == 0


def test_forever_loop_fairness_allows_other_threads(tmp_path):
    sprite_blocks = {
        "hat_forever": {"opcode": "event_whenflagclicked", "next": "forever", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "forever": {"opcode": "control_forever", "next": None, "parent": "hat_forever", "inputs": {"SUBSTACK": [2, "inc"]}, "fields": {}, "topLevel": False},
        "inc": {"opcode": "data_changevariableby", "next": None, "parent": "forever", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["hits", "sv1"]}, "topLevel": False},
        "hat_once": {"opcode": "event_whenflagclicked", "next": "set_flag", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_flag": {"opcode": "data_setvariableto", "next": None, "parent": "hat_once", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["flag", "sv2"]}, "topLevel": False},
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["hits", 0], "sv2": ["flag", 0]}
    path = tmp_path / "fairness.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.2)
    snapshot = vm.snapshot()

    assert snapshot["targets"]["Sprite1"]["variables"]["flag"] == 1
    assert snapshot["targets"]["Sprite1"]["variables"]["hits"] > 0


def test_warp_procedure_runs_without_cooperative_yield(tmp_path):
    blocks = {
        "hat1": {"opcode": "event_whenflagclicked", "next": "warp_call", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_procedure_call(
            "warp_call",
            proccode="warp add",
            arg_values={},
            next_block="capture",
            parent="hat1",
        ),
        "capture": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "warp_call",
            "inputs": {"VALUE": [3, "score_var"]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
        "score_var": {
            "opcode": "data_variable",
            "next": None,
            "parent": "capture",
            "inputs": {},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "hat2": {"opcode": "event_whenflagclicked", "next": "late_add", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "late_add": {
            "opcode": "data_changevariableby",
            "next": None,
            "parent": "hat2",
            "inputs": {"VALUE": [1, [4, "100"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        **_procedure_definition(
            "warp_def",
            "warp_proto",
            "repeat",
            proccode="warp add",
            arg_ids=[],
            arg_names=[],
            defaults=[],
            warp=True,
        ),
        "repeat": {
            "opcode": "control_repeat",
            "next": None,
            "parent": "warp_def",
            "inputs": {"TIMES": [1, [4, "3"]], "SUBSTACK": [2, "warp_inc"]},
            "fields": {},
            "topLevel": False,
        },
        "warp_inc": {
            "opcode": "data_changevariableby",
            "next": None,
            "parent": "repeat",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "warp.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.2)

    assert vm.state.stage_variables["score"] == 103.0
    assert vm.state.stage_variables["done"] == 3.0


def test_recursive_procedure_hits_depth_limit_without_stopping_other_threads(tmp_path):
    blocks = {
        "hat1": {"opcode": "event_whenflagclicked", "next": "recurse_call", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_procedure_call(
            "recurse_call",
            proccode="recurse",
            arg_values={},
            parent="hat1",
        ),
        "hat2": {"opcode": "event_whenflagclicked", "next": "done_set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "done_set": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat2",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
        **_procedure_definition(
            "recurse_def",
            "recurse_proto",
            "self_call",
            proccode="recurse",
            arg_ids=[],
            arg_names=[],
            defaults=[],
        ),
        **_procedure_call(
            "self_call",
            proccode="recurse",
            arg_values={},
            parent="recurse_def",
        ),
    }
    path = tmp_path / "recurse.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path), max_call_depth=4)
    vm.run_for(0.2)
    snapshot = vm.snapshot()

    assert vm.state.stage_variables["done"] == 1
    assert snapshot["runtime_diagnostics"] == [
        {
            "kind": "recursion_limit",
            "message": "Procedure call depth exceeded limit 4",
            "target": "Stage",
            "thread_id": 1,
            "proccode": "recurse",
            "depth": 5,
            "instance_id": 1,
        }
    ]


def test_clone_creation_copies_local_state_and_runs_clone_start(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set_local", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_local": {
            "opcode": "data_setvariableto",
            "next": "clone_self",
            "parent": "hat",
            "inputs": {"VALUE": [1, [4, "5"]]},
            "fields": {"VARIABLE": ["local", "sv1"]},
            "topLevel": False,
        },
        **_create_clone("clone_self", "myself", parent="set_local"),
        "clone_hat": {"opcode": "control_start_as_clone", "next": "clone_bump", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "clone_bump": {
            "opcode": "data_changevariableby",
            "next": "clone_move",
            "parent": "clone_hat",
            "inputs": {"VALUE": [1, [4, "3"]]},
            "fields": {"VARIABLE": ["local", "sv1"]},
            "topLevel": False,
        },
        "clone_move": {
            "opcode": "motion_setx",
            "next": None,
            "parent": "clone_bump",
            "inputs": {"X": [1, [4, "42"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["local", 0]}

    path = tmp_path / "clone_local.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.3)
    snapshot = vm.snapshot()

    assert snapshot["clone_count"] == 1
    sprite_original = snapshot["targets"]["Sprite1"]
    assert sprite_original["variables"]["local"] == 5
    clone_instances = [item for item in snapshot["instances"].values() if item["source_target_name"] == "Sprite1" and item["is_clone"]]
    assert len(clone_instances) == 1
    assert clone_instances[0]["variables"]["local"] == 8.0
    assert clone_instances[0]["x"] == 42.0


def test_named_clone_and_broadcast_reaches_original_and_clone_instances(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "clone_sprite", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_create_clone("clone_sprite", "Sprite1", next_block="broadcast_go", parent="hat"),
        "broadcast_go": {
            "opcode": "event_broadcastandwait",
            "next": None,
            "parent": "clone_sprite",
            "inputs": {"BROADCAST_INPUT": [1, [10, "go"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    sprite_blocks = {
        "clone_hat": {"opcode": "control_start_as_clone", "next": "set_clone", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_clone": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "clone_hat",
            "inputs": {"VALUE": [1, [4, "10"]]},
            "fields": {"VARIABLE": ["hits", "sv1"]},
            "topLevel": False,
        },
        "broadcast_hat": {
            "opcode": "event_whenbroadcastreceived",
            "next": "inc_hits",
            "parent": None,
            "inputs": {},
            "fields": {"BROADCAST_OPTION": ["go", "b1"]},
            "topLevel": True,
        },
        "inc_hits": {
            "opcode": "data_changevariableby",
            "next": None,
            "parent": "broadcast_hat",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["hits", "sv1"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks, blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["hits", 0]}
    path = tmp_path / "clone_broadcast.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.5)
    snapshot = vm.snapshot()

    sprite_instances = [item for item in snapshot["instances"].values() if item["source_target_name"] == "Sprite1"]
    assert len(sprite_instances) == 2
    originals = [item for item in sprite_instances if not item["is_clone"]]
    clones = [item for item in sprite_instances if item["is_clone"]]
    assert originals[0]["variables"]["hits"] == 1.0
    assert clones[0]["variables"]["hits"] == 11.0


def test_delete_this_clone_removes_clone_and_non_clone_delete_diagnoses(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "delete_original", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "delete_original": {
            "opcode": "control_delete_this_clone",
            "next": "spawn_clone",
            "parent": "hat",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        **_create_clone("spawn_clone", "myself", parent="delete_original"),
        "clone_hat": {"opcode": "control_start_as_clone", "next": "delete_clone", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "delete_clone": {
            "opcode": "control_delete_this_clone",
            "next": None,
            "parent": "clone_hat",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "delete_clone.sb3"
    write_sb3(path, _base_project(blocks_sprite=sprite_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.4)
    snapshot = vm.snapshot()

    assert snapshot["clone_count"] == 0
    assert len([item for item in snapshot["instances"].values() if item["source_target_name"] == "Sprite1"]) == 1
    assert snapshot["runtime_diagnostics"] == [
        {
            "kind": "delete_non_clone",
            "message": "delete this clone called on a non-clone instance",
            "target": "Sprite1",
            "thread_id": 1,
            "proccode": None,
            "depth": None,
            "instance_id": 2,
        }
    ]


def test_clone_start_can_call_procedure_and_clone_limit_is_enforced(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "spawn_a", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_create_clone("spawn_a", "myself", next_block="spawn_b", parent="hat"),
        **_create_clone("spawn_b", "myself", parent="spawn_a"),
        "clone_hat": {"opcode": "control_start_as_clone", "next": "proc_call", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_procedure_call("proc_call", proccode="bump", arg_values={}, parent="clone_hat"),
        **_procedure_definition(
            "proc_def",
            "proc_proto",
            "inc_hits",
            proccode="bump",
            arg_ids=[],
            arg_names=[],
            defaults=[],
        ),
        "inc_hits": {
            "opcode": "data_changevariableby",
            "next": None,
            "parent": "proc_def",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["hits", "sv1"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["hits", 0]}
    path = tmp_path / "clone_proc_limit.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path), max_clones=1)
    vm.run_for(0.4)
    snapshot = vm.snapshot()

    clone_instances = [item for item in snapshot["instances"].values() if item["source_target_name"] == "Sprite1" and item["is_clone"]]
    assert len(clone_instances) == 1
    assert clone_instances[0]["variables"]["hits"] == 1.0
    assert snapshot["runtime_diagnostics"] == [
        {
            "kind": "clone_limit",
            "message": "Clone limit 1 reached",
            "target": "Sprite1",
            "thread_id": 1,
            "proccode": None,
            "depth": None,
            "instance_id": 2,
        }
    ]


def test_timer_reset_and_snapshot_input_state(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "wait", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "wait": {
            "opcode": "control_wait",
            "next": "reset",
            "parent": "hat",
            "inputs": {"DURATION": [1, [4, "0.2"]]},
            "fields": {},
            "topLevel": False,
        },
        "reset": {"opcode": "sensing_resettimer", "next": "post_wait", "parent": "wait", "inputs": {}, "fields": {}, "topLevel": False},
        "post_wait": {
            "opcode": "control_wait",
            "next": "store_timer",
            "parent": "reset",
            "inputs": {"DURATION": [1, [4, "0.1"]]},
            "fields": {},
            "topLevel": False,
        },
        "store_timer": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "post_wait",
            "inputs": {"VALUE": [3, "timer_value"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "timer_value": {
            "opcode": "sensing_timer",
            "next": None,
            "parent": "store_timer",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    provider = HeadlessInputProvider(mouse_x_value=3.0, mouse_y_value=-8.0, mouse_down_value=True)
    path = tmp_path / "timer.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path), input_provider=provider)
    vm.run_for(0.5)
    snapshot = vm.snapshot()

    assert vm.state.stage_variables["score"] == pytest.approx(0.17, abs=0.08)
    assert snapshot["timer_seconds"] > vm.state.stage_variables["score"]
    assert snapshot["input_state"]["mouse_x"] == 3.0
    assert snapshot["input_state"]["mouse_down"] is True


def test_timer_can_use_provider_override(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store_timer", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store_timer": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [3, "timer_value"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "timer_value": {
            "opcode": "sensing_timer",
            "next": None,
            "parent": "store_timer",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    provider = HeadlessInputProvider(timer_override_value=9.25)
    path = tmp_path / "timer_override.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path), input_provider=provider)
    vm.run_for(0.2)

    assert vm.state.stage_variables["score"] == 9.25
    assert vm.snapshot()["timer_seconds"] == 9.25


def test_ask_and_wait_blocks_until_injected_answer(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "ask", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "ask": {
            "opcode": "sensing_askandwait",
            "next": "store_answer",
            "parent": "hat",
            "inputs": {"QUESTION": [1, [10, "name?"]]},
            "fields": {},
            "topLevel": False,
        },
        "store_answer": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "ask",
            "inputs": {"VALUE": [3, "answer_value"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "answer_value": {
            "opcode": "sensing_answer",
            "next": None,
            "parent": "store_answer",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    provider = HeadlessInputProvider()
    path = tmp_path / "ask.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path), input_provider=provider)
    vm.start_green_flag()
    vm.step(1 / 30)
    mid_snapshot = vm.snapshot()

    assert vm.state.stage_variables["score"] == 0
    assert mid_snapshot["thread_frames"]["1"]["waiting_for_answer"] == "name?"

    provider.answers.append("Ada")
    vm.step(1 / 30)

    assert vm.state.stage_variables["score"] == "Ada"
    assert vm.snapshot()["input_state"]["answer"] == "Ada"


def test_key_mouse_and_seeded_random_sensing(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set_key", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_key": {
            "opcode": "data_setvariableto",
            "next": "set_mouse_x",
            "parent": "hat",
            "inputs": {"VALUE": [3, "space_pressed"]},
            "fields": {"VARIABLE": ["key_state", "sv1"]},
            "topLevel": False,
        },
        "space_pressed": {
            "opcode": "sensing_keypressed",
            "next": None,
            "parent": "set_key",
            "inputs": {"KEY_OPTION": [1, "space_menu"]},
            "fields": {},
            "topLevel": False,
        },
        **_key_menu("space_menu", "space", parent="space_pressed"),
        "set_mouse_x": {
            "opcode": "data_setvariableto",
            "next": "set_mouse_y",
            "parent": "set_key",
            "inputs": {"VALUE": [3, "mouse_x_expr"]},
            "fields": {"VARIABLE": ["mouse_x_seen", "sv2"]},
            "topLevel": False,
        },
        "mouse_x_expr": {
            "opcode": "sensing_mousex",
            "next": None,
            "parent": "set_mouse_x",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        "set_mouse_y": {
            "opcode": "data_setvariableto",
            "next": "set_mouse_down",
            "parent": "set_mouse_x",
            "inputs": {"VALUE": [3, "mouse_y_expr"]},
            "fields": {"VARIABLE": ["mouse_y_seen", "sv3"]},
            "topLevel": False,
        },
        "mouse_y_expr": {
            "opcode": "sensing_mousey",
            "next": None,
            "parent": "set_mouse_y",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        "set_mouse_down": {
            "opcode": "data_setvariableto",
            "next": "set_random",
            "parent": "set_mouse_y",
            "inputs": {"VALUE": [3, "mouse_down_expr"]},
            "fields": {"VARIABLE": ["mouse_down_seen", "sv4"]},
            "topLevel": False,
        },
        "mouse_down_expr": {
            "opcode": "sensing_mousedown",
            "next": None,
            "parent": "set_mouse_down",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        "set_random": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "set_mouse_down",
            "inputs": {"VALUE": [3, "random_expr"]},
            "fields": {"VARIABLE": ["random_seen", "sv5"]},
            "topLevel": False,
        },
        "random_expr": {
            "opcode": "operator_random",
            "next": None,
            "parent": "set_random",
            "inputs": {"FROM": [1, [4, "1"]], "TO": [1, [4, "10"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {
        "sv1": ["key_state", 0],
        "sv2": ["mouse_x_seen", 0],
        "sv3": ["mouse_y_seen", 0],
        "sv4": ["mouse_down_seen", 0],
        "sv5": ["random_seen", 0],
    }
    provider = HeadlessInputProvider(
        pressed_keys={"space"},
        mouse_x_value=14.0,
        mouse_y_value=-9.0,
        mouse_down_value=True,
    )
    path = tmp_path / "sensing.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path), input_provider=provider, random_seed=7)
    vm.run_for(0.3)
    sprite = vm.snapshot()["targets"]["Sprite1"]["variables"]

    assert sprite["key_state"] is True
    assert sprite["mouse_x_seen"] == 14.0
    assert sprite["mouse_y_seen"] == -9.0
    assert sprite["mouse_down_seen"] is True
    assert sprite["random_seen"] == 6


def test_cli_run_snapshot_includes_input_state_defaults(tmp_path):
    path = tmp_path / "cli_snapshot.sb3"
    write_sb3(path, _base_project())

    proc = subprocess.run(
        [sys.executable, "-m", "sb3vm.cli", "run", str(path), "--seconds", "0.1"],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert payload["input_state"]["answer"] == ""
    assert payload["input_state"]["pressed_keys"] == []
    assert payload["input_state"]["random_seed"] is None


def test_render_snapshot_exposes_renderer_ready_visual_state(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "switch_backdrop", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "switch_backdrop": {
            "opcode": "looks_switchbackdropto",
            "next": None,
            "parent": "hat",
            "inputs": {"BACKDROP": [1, [10, "night"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "show", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "show": {"opcode": "looks_show", "next": "switch_costume", "parent": "hat", "inputs": {}, "fields": {}, "topLevel": False},
        "switch_costume": {
            "opcode": "looks_switchcostumeto",
            "next": "front",
            "parent": "show",
            "inputs": {"COSTUME": [1, [10, "run"]]},
            "fields": {},
            "topLevel": False,
        },
        "front": {"opcode": "looks_gotofrontback", "next": None, "parent": "switch_costume", "inputs": {}, "fields": {"FRONT_BACK": ["front", None]}, "topLevel": False},
    }
    project = _base_project(blocks_stage=stage_blocks, blocks_sprite=sprite_blocks)
    project["targets"][0]["costumes"] = [
        {"name": "day", "assetId": "bg1", "md5ext": "bg1.svg"},
        {"name": "night", "assetId": "bg2", "md5ext": "bg2.svg"},
    ]
    project["targets"][1]["costumes"] = [
        {"name": "idle", "assetId": "spr1", "md5ext": "spr1.svg"},
        {"name": "run", "assetId": "spr2", "md5ext": "spr2.svg"},
    ]
    project["targets"].append(
        {
            "isStage": False,
            "name": "Sprite2",
            "variables": {},
            "lists": {},
            "broadcasts": {},
            "blocks": {},
            "comments": {},
            "costumes": [{"name": "other", "assetId": "spr3", "md5ext": "spr3.svg"}],
            "sounds": [],
            "x": -10,
            "y": 5,
            "visible": False,
            "currentCostume": 0,
            "layerOrder": 0,
        }
    )
    path = tmp_path / "render_state.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.3)
    render = vm.render_snapshot()

    assert render["coordinate_system"] == {
        "name": "scratch_stage",
        "origin": "center",
        "x_axis": "right",
        "y_axis": "up",
        "stage_width": 480,
        "stage_height": 360,
    }
    assert render["layer_model"] == {
        "ordering": "back_to_front",
        "stage_is_base_layer": True,
    }
    assert render["stage"]["backdrop"] == {
        "target_name": "Stage",
        "index": 1,
        "count": 2,
        "name": "night",
        "asset_id": "bg2",
        "md5ext": "bg2.svg",
    }
    assert render["collision_boundary"]["available"] is False
    assert [item["source_target_name"] for item in render["drawables"]] == ["Sprite2", "Sprite1"]
    assert render["drawables"][1]["costume"] == {
        "target_name": "Sprite1",
        "index": 1,
        "count": 2,
        "name": "run",
        "asset_id": "spr2",
        "md5ext": "spr2.svg",
    }
    assert "variables" not in render["drawables"][0]
    assert render["drawables"][0]["collision"]["api"] == "unavailable"


def test_motion_direction_goto_and_glide_semantics(tmp_path):
    sprite1_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "point", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "point": {
            "opcode": "motion_pointtowards",
            "next": "turn",
            "parent": "hat",
            "inputs": {"TOWARDS": [1, [10, "Sprite2"]]},
            "fields": {},
            "topLevel": False,
        },
        "turn": {
            "opcode": "motion_turnright",
            "next": "style",
            "parent": "point",
            "inputs": {"DEGREES": [1, [4, "180"]]},
            "fields": {},
            "topLevel": False,
        },
        "style": {
            "opcode": "motion_setrotationstyle",
            "next": "goto_mouse",
            "parent": "turn",
            "inputs": {},
            "fields": {"STYLE": ["left-right", None]},
            "topLevel": False,
        },
        "goto_mouse": {
            "opcode": "motion_goto",
            "next": "glide",
            "parent": "style",
            "inputs": {"TO": [1, [10, "_mouse_"]]},
            "fields": {},
            "topLevel": False,
        },
        "glide": {
            "opcode": "motion_glidesecstoxy",
            "next": None,
            "parent": "goto_mouse",
            "inputs": {"SECS": [1, [4, "1"]], "X": [1, [4, "100"]], "Y": [1, [4, "-50"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    project = {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": {},
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
                "blocks": sprite1_blocks,
                "comments": {},
                "costumes": [{"name": "one"}],
                "sounds": [],
                "x": 0,
                "y": 0,
                "direction": 90,
                "visible": True,
                "currentCostume": 0,
            },
            {
                "isStage": False,
                "name": "Sprite2",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": {},
                "comments": {},
                "costumes": [{"name": "two"}],
                "sounds": [],
                "x": 0,
                "y": 100,
                "visible": True,
                "currentCostume": 0,
            },
        ],
        "monitors": [],
        "extensions": [],
        "meta": {"semver": "3.0.0"},
    }
    provider = HeadlessInputProvider(mouse_x_value=10.0, mouse_y_value=-20.0)
    path = tmp_path / "motion_semantics.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path), input_provider=provider)
    vm.start_green_flag()
    for _ in range(16):
        vm.step(1 / 30)
    mid = vm.snapshot()["targets"]["Sprite1"]

    assert mid["rotation_style"] == "left-right"
    assert mid["direction"] == 180.0
    assert mid["x"] == pytest.approx(43.0, abs=0.5)
    assert mid["y"] == pytest.approx(-31.0, abs=0.6)

    for _ in range(30):
        vm.step(1 / 30)
    final = vm.snapshot()["targets"]["Sprite1"]
    assert final["x"] == pytest.approx(100.0, abs=0.01)
    assert final["y"] == pytest.approx(-50.0, abs=0.01)


def test_random_and_named_goto_use_seeded_rng_and_original_instance(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "clone_sprite2", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_create_clone("clone_sprite2", "Sprite2", parent="hat"),
    }
    sprite1_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "goto_random", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "goto_random": {
            "opcode": "motion_goto",
            "next": "goto_named",
            "parent": "hat",
            "inputs": {"TO": [1, [10, "_random_"]]},
            "fields": {},
            "topLevel": False,
        },
        "goto_named": {
            "opcode": "motion_goto",
            "next": None,
            "parent": "goto_random",
            "inputs": {"TO": [1, [10, "Sprite2"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    sprite2_blocks = {
        "clone_hat": {"opcode": "control_start_as_clone", "next": "move_clone", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "move_clone": {
            "opcode": "motion_setx",
            "next": None,
            "parent": "clone_hat",
            "inputs": {"X": [1, [4, "100"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    project = {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": stage_blocks,
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
                "blocks": sprite1_blocks,
                "comments": {},
                "costumes": [{"name": "one"}],
                "sounds": [],
                "x": 0,
                "y": 0,
                "visible": True,
                "currentCostume": 0,
            },
            {
                "isStage": False,
                "name": "Sprite2",
                "variables": {},
                "lists": {},
                "broadcasts": {},
                "blocks": sprite2_blocks,
                "comments": {},
                "costumes": [{"name": "two"}],
                "sounds": [],
                "x": 40,
                "y": 15,
                "visible": True,
                "currentCostume": 0,
            },
        ],
        "monitors": [],
        "extensions": [],
        "meta": {"semver": "3.0.0"},
    }
    path = tmp_path / "goto_random_named.sb3"
    write_sb3(path, project)

    first = Sb3Vm(load_sb3(path), random_seed=11)
    second = Sb3Vm(load_sb3(path), random_seed=11)
    first.run_for(0.3)
    second.run_for(0.3)

    first_snapshot = first.snapshot()
    second_snapshot = second.snapshot()
    assert first_snapshot["targets"]["Sprite1"]["x"] == 40.0
    assert first_snapshot["targets"]["Sprite1"]["y"] == 15.0
    assert second_snapshot["targets"]["Sprite1"] == first_snapshot["targets"]["Sprite1"]


def test_looks_state_reporters_effects_and_layers(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "switch_backdrop", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "switch_backdrop": {
            "opcode": "looks_switchbackdropto",
            "next": "next_backdrop",
            "parent": "hat",
            "inputs": {"BACKDROP": [1, [10, "night"]]},
            "fields": {},
            "topLevel": False,
        },
        "next_backdrop": {"opcode": "looks_nextbackdrop", "next": None, "parent": "switch_backdrop", "inputs": {}, "fields": {}, "topLevel": False},
    }
    sprite1_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "switch_costume", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "switch_costume": {
            "opcode": "looks_switchcostumeto",
            "next": "next_costume",
            "parent": "hat",
            "inputs": {"COSTUME": [1, [10, "two"]]},
            "fields": {},
            "topLevel": False,
        },
        "next_costume": {"opcode": "looks_nextcostume", "next": "set_size", "parent": "switch_costume", "inputs": {}, "fields": {}, "topLevel": False},
        "set_size": {
            "opcode": "looks_setsizeto",
            "next": "change_size",
            "parent": "next_costume",
            "inputs": {"SIZE": [1, [4, "150"]]},
            "fields": {},
            "topLevel": False,
        },
        "change_size": {
            "opcode": "looks_changesizeby",
            "next": "set_effect",
            "parent": "set_size",
            "inputs": {"CHANGE": [1, [4, "-25"]]},
            "fields": {},
            "topLevel": False,
        },
        "set_effect": {
            "opcode": "looks_seteffectto",
            "next": "change_effect",
            "parent": "change_size",
            "inputs": {"VALUE": [1, [4, "10"]]},
            "fields": {"EFFECT": ["color", None]},
            "topLevel": False,
        },
        "change_effect": {
            "opcode": "looks_changeeffectby",
            "next": "clear_effects",
            "parent": "set_effect",
            "inputs": {"CHANGE": [1, [4, "5"]]},
            "fields": {"EFFECT": ["color", None]},
            "topLevel": False,
        },
        "clear_effects": {"opcode": "looks_cleargraphiceffects", "next": "set_ghost", "parent": "change_effect", "inputs": {}, "fields": {}, "topLevel": False},
        "set_ghost": {
            "opcode": "looks_seteffectto",
            "next": "to_front",
            "parent": "clear_effects",
            "inputs": {"VALUE": [1, [4, "7"]]},
            "fields": {"EFFECT": ["ghost", None]},
            "topLevel": False,
        },
        "to_front": {"opcode": "looks_gotofrontback", "next": "back_one", "parent": "set_ghost", "inputs": {}, "fields": {"FRONT_BACK": ["front", None]}, "topLevel": False},
        "back_one": {
            "opcode": "looks_goforwardbackwardlayers",
            "next": "store_costume_number",
            "parent": "to_front",
            "inputs": {"NUM": [1, [4, "1"]]},
            "fields": {"FORWARD_BACKWARD": ["backward", None]},
            "topLevel": False,
        },
        "store_costume_number": {
            "opcode": "data_setvariableto",
            "next": "store_costume_name",
            "parent": "back_one",
            "inputs": {"VALUE": [3, "costume_number_expr"]},
            "fields": {"VARIABLE": ["costume_number", "sv1"]},
            "topLevel": False,
        },
        "costume_number_expr": {
            "opcode": "looks_costumenumbername",
            "next": None,
            "parent": "store_costume_number",
            "inputs": {},
            "fields": {"NUMBER_NAME": ["number", None]},
            "topLevel": False,
        },
        "store_costume_name": {
            "opcode": "data_setvariableto",
            "next": "store_backdrop_name",
            "parent": "store_costume_number",
            "inputs": {"VALUE": [3, "costume_name_expr"]},
            "fields": {"VARIABLE": ["costume_name", "sv2"]},
            "topLevel": False,
        },
        "costume_name_expr": {
            "opcode": "looks_costumenumbername",
            "next": None,
            "parent": "store_costume_name",
            "inputs": {},
            "fields": {"NUMBER_NAME": ["name", None]},
            "topLevel": False,
        },
        "store_backdrop_name": {
            "opcode": "data_setvariableto",
            "next": "store_size",
            "parent": "store_costume_name",
            "inputs": {"VALUE": [3, "backdrop_name_expr"]},
            "fields": {"VARIABLE": ["backdrop_name", "sv3"]},
            "topLevel": False,
        },
        "backdrop_name_expr": {
            "opcode": "looks_backdropnumbername",
            "next": None,
            "parent": "store_backdrop_name",
            "inputs": {},
            "fields": {"NUMBER_NAME": ["name", None]},
            "topLevel": False,
        },
        "store_size": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "store_backdrop_name",
            "inputs": {"VALUE": [3, "size_expr"]},
            "fields": {"VARIABLE": ["size_seen", "sv4"]},
            "topLevel": False,
        },
        "size_expr": {
            "opcode": "looks_size",
            "next": None,
            "parent": "store_size",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks, blocks_sprite=sprite1_blocks)
    project["targets"][0]["costumes"] = [{"name": "day"}, {"name": "night"}]
    project["targets"][1]["costumes"] = [{"name": "one"}, {"name": "two"}, {"name": "three"}]
    project["targets"][1]["variables"] = {
        "sv1": ["costume_number", 0],
        "sv2": ["costume_name", ""],
        "sv3": ["backdrop_name", ""],
        "sv4": ["size_seen", 0],
    }
    project["targets"].append(
        {
            "isStage": False,
            "name": "Sprite2",
            "variables": {},
            "lists": {},
            "broadcasts": {},
            "blocks": {},
            "comments": {},
            "costumes": [{"name": "other"}],
            "sounds": [],
            "x": 0,
            "y": 0,
            "visible": True,
            "currentCostume": 0,
            "layerOrder": 5,
        }
    )
    path = tmp_path / "looks_state.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.6)
    snapshot = vm.snapshot()
    sprite1 = snapshot["targets"]["Sprite1"]
    sprite2 = snapshot["targets"]["Sprite2"]

    assert snapshot["targets"]["Stage"]["costume_index"] == 0
    assert sprite1["costume_index"] == 2
    assert sprite1["size"] == 125.0
    assert sprite1["effects"] == {"ghost": 7.0}
    assert sprite1["variables"]["costume_number"] == 3
    assert sprite1["variables"]["costume_name"] == "three"
    assert sprite1["variables"]["backdrop_name"] == "day"
    assert sprite1["variables"]["size_seen"] == 125.0
    assert sprite1["layer_order"] < sprite2["layer_order"]


def test_motion_reporters_and_glide_to_named_target(tmp_path):
    sprite1_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "glide", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "glide": {
            "opcode": "motion_glideto",
            "next": "store_x",
            "parent": "hat",
            "inputs": {"SECS": [1, [4, "0.1"]], "TO": [1, [10, "Sprite2"]]},
            "fields": {},
            "topLevel": False,
        },
        "store_x": {
            "opcode": "data_setvariableto",
            "next": "store_y",
            "parent": "glide",
            "inputs": {"VALUE": [3, "x_expr"]},
            "fields": {"VARIABLE": ["x_seen", "sv1"]},
            "topLevel": False,
        },
        "x_expr": {"opcode": "motion_xposition", "next": None, "parent": "store_x", "inputs": {}, "fields": {}, "topLevel": False},
        "store_y": {
            "opcode": "data_setvariableto",
            "next": "store_direction",
            "parent": "store_x",
            "inputs": {"VALUE": [3, "y_expr"]},
            "fields": {"VARIABLE": ["y_seen", "sv2"]},
            "topLevel": False,
        },
        "y_expr": {"opcode": "motion_yposition", "next": None, "parent": "store_y", "inputs": {}, "fields": {}, "topLevel": False},
        "store_direction": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "store_y",
            "inputs": {"VALUE": [3, "direction_expr"]},
            "fields": {"VARIABLE": ["direction_seen", "sv3"]},
            "topLevel": False,
        },
        "direction_expr": {"opcode": "motion_direction", "next": None, "parent": "store_direction", "inputs": {}, "fields": {}, "topLevel": False},
    }
    project = _base_project(blocks_sprite=sprite1_blocks)
    project["targets"][1]["variables"] = {
        "sv1": ["x_seen", 0],
        "sv2": ["y_seen", 0],
        "sv3": ["direction_seen", 0],
    }
    project["targets"].append(
        {
            "isStage": False,
            "name": "Sprite2",
            "variables": {},
            "lists": {},
            "broadcasts": {},
            "blocks": {},
            "comments": {},
            "costumes": [{"name": "other"}],
            "sounds": [],
            "x": -30,
            "y": 45,
            "visible": True,
            "currentCostume": 0,
        }
    )
    path = tmp_path / "motion_reporters.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.3)
    variables = vm.snapshot()["targets"]["Sprite1"]["variables"]

    assert variables["x_seen"] == -30.0
    assert variables["y_seen"] == 45.0
    assert variables["direction_seen"] == 90
