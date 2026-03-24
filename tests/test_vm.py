from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def test_sprite_click_trigger_runs_for_clicked_sprite(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenthisspriteclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, [4, "5"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "sprite_click.sb3"
    write_sb3(path, _base_project(blocks_sprite=sprite_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.emit_sprite_click(vm.state.get_original_instance_id("Sprite1"))
    vm.step(0.0)

    assert vm.state.stage_variables["score"] == 5.0


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

    assert inspect["opcode_coverage"]["unsupported_by_opcode"] == {"gdxfor_getAcceleration": 1}
    assert inspect["unsupported_scripts"] == [
        {
            "target": "Stage",
            "trigger": "green_flag",
            "value": None,
            "node_kind": "statement",
            "opcode": "gdxfor_getAcceleration",
            "reason": "unsupported statement opcode",
            "block_id": "move",
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


def test_snapshot_reports_current_statement_status(tmp_path):
    blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "wait", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "wait": {"opcode": "control_wait", "next": None, "parent": "hat", "inputs": {"DURATION": [1, [4, "0.2"]]}, "fields": {}, "topLevel": False},
    }
    path = tmp_path / "thread_status.sb3"
    write_sb3(path, _base_project(blocks_stage=blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.start_green_flag()
    snapshot = vm.snapshot()

    assert snapshot["thread_status"][0]["current_statement"] == "wait(0.2)"
    assert snapshot["thread_frames"]["1"]["current_statement"] == "wait(0.2)"


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
    assert payload["opcode_coverage"]["by_opcode"]["gdxfor_getAcceleration"] == 1
    assert payload["unsupported_scripts"][0]["opcode"] == "gdxfor_getAcceleration"


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


def test_clone_creation_accepts_raw_myself_menu_value(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "clone_self", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        **_create_clone("clone_self", "_myself_", parent="hat"),
        "clone_hat": {"opcode": "control_start_as_clone", "next": "set_local", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_local": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "clone_hat",
            "inputs": {"VALUE": [1, [4, "9"]]},
            "fields": {"VARIABLE": ["local", "sv1"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["local", 0]}

    path = tmp_path / "clone_myself_menu.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.2)
    snapshot = vm.snapshot()

    clone_instances = [item for item in snapshot["instances"].values() if item["source_target_name"] == "Sprite1" and item["is_clone"]]
    assert len(clone_instances) == 1
    assert clone_instances[0]["variables"]["local"] == 9.0
    assert snapshot["runtime_diagnostics"] == []


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


def test_when_key_pressed_hat_fires_on_press_edges_only(tmp_path):
    sprite_blocks = {
        "hat": {
            "opcode": "event_whenkeypressed",
            "next": "inc",
            "parent": None,
            "inputs": {},
            "fields": {"KEY_OPTION": ["space", None]},
            "topLevel": True,
        },
        "inc": {
            "opcode": "data_changevariableby",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["hits", "sv1"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["hits", 0]}
    provider = HeadlessInputProvider()
    path = tmp_path / "when_key_pressed.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path), input_provider=provider)
    vm.step(1 / 30)
    assert vm.snapshot()["targets"]["Sprite1"]["variables"]["hits"] == 0

    provider.pressed_keys.add("space")
    vm.step(1 / 30)
    assert vm.snapshot()["targets"]["Sprite1"]["variables"]["hits"] == 1.0

    vm.step(1 / 30)
    assert vm.snapshot()["targets"]["Sprite1"]["variables"]["hits"] == 1.0

    provider.pressed_keys.clear()
    vm.step(1 / 30)
    provider.pressed_keys.add("space")
    vm.step(1 / 30)

    assert vm.snapshot()["targets"]["Sprite1"]["variables"]["hits"] == 2.0


def test_dialogue_blocks_update_snapshot_and_render_state(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "say", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "say": {
            "opcode": "looks_say",
            "next": None,
            "parent": "hat",
            "inputs": {"MESSAGE": [1, [10, "ready"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "think", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "think": {
            "opcode": "looks_thinkforsecs",
            "next": None,
            "parent": "hat",
            "inputs": {"MESSAGE": [1, [10, "hmm"]], "SECS": [1, [4, "0.1"]]},
            "fields": {},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks, blocks_sprite=sprite_blocks)
    path = tmp_path / "dialogue.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.start_green_flag()
    vm.step(1 / 30)

    snapshot = vm.snapshot()
    render = vm.render_snapshot()
    sprite_render = next(item for item in render["drawables"] if item["source_target_name"] == "Sprite1")

    assert snapshot["targets"]["Stage"]["dialogue"] == {"style": "say", "text": "ready"}
    assert snapshot["targets"]["Sprite1"]["dialogue"] == {"style": "think", "text": "hmm"}
    assert render["stage"]["dialogue"] == {"style": "say", "text": "ready"}
    assert sprite_render["dialogue"] == {"style": "think", "text": "hmm"}

    for _ in range(3):
        vm.step(1 / 30)

    assert vm.snapshot()["targets"]["Stage"]["dialogue"] == {"style": "say", "text": "ready"}
    assert vm.snapshot()["targets"]["Sprite1"]["dialogue"] is None


def test_when_backdrop_switches_to_and_switch_backdrop_wait(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "switch_wait", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "switch_wait": {
            "opcode": "looks_switchbackdroptoandwait",
            "next": "done",
            "parent": "hat",
            "inputs": {"BACKDROP": [1, [10, "night"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "switch_wait",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    sprite_blocks = {
        "hat": {
            "opcode": "event_whenbackdropswitchesto",
            "next": "wait",
            "parent": None,
            "inputs": {},
            "fields": {"BACKDROP": ["night", None]},
            "topLevel": True,
        },
        "wait": {
            "opcode": "control_wait",
            "next": "set_score",
            "parent": "hat",
            "inputs": {"DURATION": [1, [4, "0.1"]]},
            "fields": {},
            "topLevel": False,
        },
        "set_score": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "wait",
            "inputs": {"VALUE": [1, [4, "7"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks, blocks_sprite=sprite_blocks)
    project["targets"][0]["costumes"] = [{"name": "day"}, {"name": "night"}]
    path = tmp_path / "backdrop_wait.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.start_green_flag()
    vm.step(1 / 30)
    first = vm.snapshot()

    assert first["targets"]["Stage"]["costume_index"] == 1
    assert first["stage_variables"]["score"] == 0
    assert first["stage_variables"]["done"] == 0

    for _ in range(2):
        vm.step(1 / 30)
    third = vm.snapshot()
    assert third["stage_variables"]["done"] == 0

    for _ in range(5):
        vm.step(1 / 30)
    final = vm.snapshot()

    assert final["stage_variables"]["score"] == 7.0
    assert final["stage_variables"]["done"] == 1


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


def test_looks_costume_shadow_switches_costume(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "switch", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "switch": {
            "opcode": "looks_switchcostumeto",
            "next": None,
            "parent": "hat",
            "inputs": {"COSTUME": [1, "costume_menu"]},
            "fields": {},
            "topLevel": False,
        },
        "costume_menu": {
            "opcode": "looks_costume",
            "next": None,
            "parent": "switch",
            "inputs": {},
            "fields": {"COSTUME": ["two", None]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["costumes"] = [{"name": "one"}, {"name": "two"}]
    path = tmp_path / "looks_costume_menu.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path), enable_compilation=True, lazy_compile_threshold=1)
    vm.run_for(0.2)

    assert vm.snapshot()["targets"]["Sprite1"]["costume_index"] == 1


def test_music_note_shadow_waits_for_beats_and_compiles(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "note_stmt", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "note_stmt": {
            "opcode": "music_playNoteForBeats",
            "next": "done",
            "parent": "hat",
            "inputs": {"NOTE": [1, "note_shadow"], "BEATS": [1, [4, "0.25"]]},
            "fields": {},
            "topLevel": False,
        },
        "note_shadow": {
            "opcode": "note",
            "next": None,
            "parent": "note_stmt",
            "inputs": {},
            "fields": {"NOTE": ["36", None]},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "note_stmt",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks)
    project["targets"][0]["tempo"] = 120
    path = tmp_path / "music_note_wait.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path), enable_compilation=True, lazy_compile_threshold=1)
    vm.start_green_flag()
    for _ in range(3):
        vm.step(1 / 30)
    assert vm.state.stage_variables["done"] == 0

    for _ in range(2):
        vm.step(1 / 30)
    assert vm.state.stage_variables["done"] == 1


def test_touching_object_mouse_menu_support_and_compiles(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [3, "touch_expr"]},
            "fields": {"VARIABLE": ["touching_mouse", "sv1"]},
            "topLevel": False,
        },
        "touch_expr": {
            "opcode": "sensing_touchingobject",
            "next": None,
            "parent": "store",
            "inputs": {"TOUCHINGOBJECTMENU": [1, "touch_menu"]},
            "fields": {},
            "topLevel": False,
        },
        "touch_menu": {
            "opcode": "sensing_touchingobjectmenu",
            "next": None,
            "parent": "touch_expr",
            "inputs": {},
            "fields": {"TOUCHINGOBJECTMENU": ["_mouse_", None]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["variables"] = {"sv1": ["touching_mouse", 0]}
    project["targets"][1]["costumes"] = [{"name": "one", "rotationCenterX": 10, "rotationCenterY": 10}]
    path = tmp_path / "touching_mouse.sb3"
    write_sb3(path, project)

    provider = HeadlessInputProvider(mouse_x_value=5.0, mouse_y_value=-5.0)
    vm = Sb3Vm(load_sb3(path), input_provider=provider, enable_compilation=True, lazy_compile_threshold=1)
    vm.run_for(0.2)

    assert vm.snapshot()["targets"]["Sprite1"]["variables"]["touching_mouse"] is True


def test_inspect_test_sb3_has_no_unsupported_scripts():
    fixture = Path(__file__).resolve().parent.parent / "test.sb3"

    vm = Sb3Vm(load_sb3(fixture))
    inspect = vm.inspect()

    assert inspect["opcode_coverage"]["unsupported_by_opcode"] == {}
    assert inspect["unsupported_scripts"] == []


# ---------------------------------------------------------------------------
# New compatibility opcode tests
# ---------------------------------------------------------------------------


def test_control_wait_until_blocks_until_condition(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "wu", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "wu": {
            "opcode": "control_wait_until",
            "next": "done",
            "parent": "hat",
            "inputs": {"CONDITION": [2, "cond"]},
            "fields": {},
            "topLevel": False,
        },
        "cond": {
            "opcode": "operator_gt",
            "next": None,
            "parent": "wu",
            "inputs": {
                "OPERAND1": [3, "var_ref"],
                "OPERAND2": [1, [4, "5"]],
            },
            "fields": {},
            "topLevel": False,
        },
        "var_ref": {"opcode": "data_variable", "next": None, "parent": "cond", "inputs": {}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "wu",
            "inputs": {"VALUE": [1, [4, "99"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    hat2_blocks = {
        "hat2": {"opcode": "event_whenflagclicked", "next": "inc", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "inc": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat2",
            "inputs": {"VALUE": [1, [4, "10"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks | hat2_blocks)
    path = tmp_path / "wait_until.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.5)

    snap = vm.snapshot()
    assert snap["stage_variables"]["done"] == 99.0
    assert snap["stage_variables"]["score"] == 10.0


def test_motion_ifedgebounce_reflects_direction(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "bounce", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "bounce": {"opcode": "motion_ifedgebounce", "next": None, "parent": "hat", "inputs": {}, "fields": {}, "topLevel": False},
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["x"] = 260.0
    project["targets"][1]["direction"] = 90.0
    project["targets"][1]["costumes"] = [{"name": "one", "rotationCenterX": 5, "rotationCenterY": 5}]
    path = tmp_path / "edge_bounce.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    snap = vm.snapshot()["targets"]["Sprite1"]
    assert snap["x"] <= 240.0
    assert snap["direction"] != 90.0


def test_sensing_of_reads_sprite_position(tmp_path):
    sprite2_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [3, "of_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "of_expr": {
            "opcode": "sensing_of",
            "next": None,
            "parent": "store",
            "inputs": {"OBJECT": [1, "obj_menu"]},
            "fields": {"PROPERTY": ["x position", None]},
            "topLevel": False,
        },
        "obj_menu": {
            "opcode": "sensing_of_object_menu",
            "next": None,
            "parent": "of_expr",
            "inputs": {},
            "fields": {"OBJECT": ["Sprite1", None]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=sprite2_blocks)
    project["targets"][1]["x"] = 55.0
    path = tmp_path / "sensing_of.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.snapshot()["stage_variables"]["score"] == 55.0


def test_sensing_distanceto_returns_correct_distance(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [3, "dist_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "dist_expr": {
            "opcode": "sensing_distanceto",
            "next": None,
            "parent": "store",
            "inputs": {"DISTANCETOMENU": [1, "dist_menu"]},
            "fields": {},
            "topLevel": False,
        },
        "dist_menu": {
            "opcode": "sensing_distancetomenu",
            "next": None,
            "parent": "dist_expr",
            "inputs": {},
            "fields": {"DISTANCETOMENU": ["_mouse_", None]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["x"] = 30.0
    project["targets"][1]["y"] = 40.0
    project["targets"][1]["variables"] = {"sv1": ["score", 0]}
    path = tmp_path / "distanceto.sb3"
    write_sb3(path, project)

    provider = HeadlessInputProvider(mouse_x_value=30.0, mouse_y_value=40.0)
    vm = Sb3Vm(load_sb3(path), input_provider=provider)
    vm.run_for(0.1)

    assert vm.snapshot()["targets"]["Sprite1"]["variables"]["score"] == 0.0


def test_sensing_current_returns_int(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [3, "cur_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "cur_expr": {
            "opcode": "sensing_current",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {"CURRENTMENU": ["YEAR", None]},
            "topLevel": False,
        },
    }
    path = tmp_path / "current.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    year = vm.snapshot()["stage_variables"]["score"]
    assert isinstance(year, int)
    assert year >= 2024


def test_sensing_dayssince2000_returns_positive_float(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [3, "days_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "days_expr": {
            "opcode": "sensing_dayssince2000",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "dayssince2000.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    days = vm.snapshot()["stage_variables"]["score"]
    assert days > 9000


def test_event_whengreaterthan_fires_on_timer_threshold(tmp_path):
    stage_blocks = {
        "hat": {
            "opcode": "event_whengreaterthan",
            "next": "set",
            "parent": None,
            "inputs": {"VALUE": [1, [4, "0.05"]]},
            "fields": {"WHENGREATERTHANMENU": ["TIMER", None]},
            "topLevel": True,
        },
        "set": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "whengreaterthan.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.start_green_flag()
    for _ in range(4):
        vm.step(1 / 30)

    assert vm.snapshot()["stage_variables"]["done"] == 1.0


def test_sound_blocks_are_no_ops_and_not_unsupported(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "snd", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "snd": {
            "opcode": "sound_play",
            "next": "vol",
            "parent": "hat",
            "inputs": {"SOUND_MENU": [1, "smenu"]},
            "fields": {},
            "topLevel": False,
        },
        "smenu": {
            "opcode": "sound_sounds_menu",
            "next": None,
            "parent": "snd",
            "inputs": {},
            "fields": {"SOUND_MENU": ["pop", None]},
            "topLevel": False,
        },
        "vol": {
            "opcode": "sound_setvolumeto",
            "next": "set",
            "parent": "snd",
            "inputs": {"VOLUME": [1, [4, "80"]]},
            "fields": {},
            "topLevel": False,
        },
        "set": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "vol",
            "inputs": {"VALUE": [1, [4, "7"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "sound_noop.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    snap = vm.snapshot()
    assert snap["stage_variables"]["score"] == 7.0
    assert vm.inspect()["unsupported_scripts"] == []


def test_data_show_hide_variable_are_no_ops(tmp_path):
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "show", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "show": {
            "opcode": "data_showvariable",
            "next": "hide",
            "parent": "hat",
            "inputs": {},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "hide": {
            "opcode": "data_hidevariable",
            "next": "set",
            "parent": "show",
            "inputs": {},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "set": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hide",
            "inputs": {"VALUE": [1, [4, "3"]]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "show_hide.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.snapshot()["stage_variables"]["score"] == 3.0
    assert vm.inspect()["unsupported_scripts"] == []


def test_motion_movesteps_moves_in_direction(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "move", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "move": {"opcode": "motion_movesteps", "next": None, "parent": "hat", "inputs": {"STEPS": [1, [4, "10"]]}, "fields": {}, "topLevel": False},
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    project["targets"][1]["direction"] = 90.0  # facing right
    project["targets"][1]["x"] = 0.0
    project["targets"][1]["y"] = 0.0
    path = tmp_path / "movesteps.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    snap = vm.snapshot()["targets"]["Sprite1"]
    assert abs(snap["x"] - 10.0) < 0.001
    assert abs(snap["y"] - 0.0) < 0.001
    assert vm.inspect()["unsupported_scripts"] == []


def test_motion_goto_with_menu_not_unsupported(tmp_path):
    sprite_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "goto", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "goto": {"opcode": "motion_goto", "next": None, "parent": "hat", "inputs": {"TO": [1, "menu"]}, "fields": {}, "topLevel": False},
        "menu": {"opcode": "motion_goto_menu", "next": None, "parent": "goto", "inputs": {}, "fields": {"TO": ["_random_", None]}, "topLevel": False},
    }
    project = _base_project(blocks_sprite=sprite_blocks)
    path = tmp_path / "goto_menu.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.inspect()["unsupported_scripts"] == []


# ---------------------------------------------------------------------------
# Extension system tests
# ---------------------------------------------------------------------------

def test_pen_opcodes_are_no_ops_and_not_unsupported(tmp_path):
    """Pen drawing blocks run without error and don't mark scripts unsupported."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "pen_down", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "pen_down": {"opcode": "pen_penDown", "next": "pen_up", "parent": "hat", "inputs": {}, "fields": {}, "topLevel": False},
        "pen_up": {"opcode": "pen_penUp", "next": "stamp", "parent": "pen_down", "inputs": {}, "fields": {}, "topLevel": False},
        "stamp": {"opcode": "pen_stamp", "next": "clear", "parent": "pen_up", "inputs": {}, "fields": {}, "topLevel": False},
        "clear": {"opcode": "pen_clear", "next": "done", "parent": "stamp", "inputs": {}, "fields": {}, "topLevel": False},
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "clear",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "pen_noop.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.3)

    assert vm.state.stage_variables["done"] == 1
    assert vm.inspect()["unsupported_scripts"] == []


def test_music_play_drum_waits_for_beats(tmp_path):
    """music_playDrumForBeats blocks execution until the beat duration elapses."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "drum", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "drum": {
            "opcode": "music_playDrumForBeats",
            "next": "done",
            "parent": "hat",
            "inputs": {
                "DRUM": [1, "drum_menu"],
                "BEATS": [1, [4, "0.5"]],
            },
            "fields": {},
            "topLevel": False,
        },
        "drum_menu": {
            "opcode": "music_menu_DRUM",
            "next": None,
            "parent": "drum",
            "inputs": {},
            "fields": {"DRUM": ["1", None]},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "drum",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks)
    project["targets"][0]["tempo"] = 60  # 1 beat = 1 second; 0.5 beats = 0.5 s
    path = tmp_path / "drum_wait.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.start_green_flag()
    vm.step(1 / 30)
    assert vm.state.stage_variables["done"] == 0  # still waiting

    for _ in range(20):
        vm.step(1 / 30)
    assert vm.state.stage_variables["done"] == 1


def test_music_rest_waits_for_beats(tmp_path):
    """music_restForBeats delays execution by the given beat count."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "rest", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "rest": {
            "opcode": "music_restForBeats",
            "next": "done",
            "parent": "hat",
            "inputs": {"BEATS": [1, [4, "1"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "rest",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks)
    project["targets"][0]["tempo"] = 120  # 1 beat = 0.5 s
    path = tmp_path / "rest_wait.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.start_green_flag()
    vm.step(1 / 30)
    assert vm.state.stage_variables["done"] == 0  # still waiting

    for _ in range(25):
        vm.step(1 / 30)
    assert vm.state.stage_variables["done"] == 1


def test_music_set_and_get_tempo(tmp_path):
    """music_setTempo updates vm.state.music_tempo; music_getTempo reads it back."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set_tempo", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_tempo": {
            "opcode": "music_setTempo",
            "next": "store",
            "parent": "hat",
            "inputs": {"TEMPO": [1, [4, "180"]]},
            "fields": {},
            "topLevel": False,
        },
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "set_tempo",
            "inputs": {"VALUE": [1, "tempo_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "tempo_expr": {
            "opcode": "music_getTempo",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "set_tempo.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.music_tempo == 180.0
    assert vm.state.stage_variables["score"] == 180.0
    assert vm.inspect()["unsupported_scripts"] == []


def test_music_change_tempo(tmp_path):
    """music_changeTempo adjusts music_tempo by a delta."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "change", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "change": {
            "opcode": "music_changeTempo",
            "next": "store",
            "parent": "hat",
            "inputs": {"TEMPO": [1, [4, "20"]]},
            "fields": {},
            "topLevel": False,
        },
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "change",
            "inputs": {"VALUE": [1, "tempo_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "tempo_expr": {
            "opcode": "music_getTempo",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    project = _base_project(blocks_stage=stage_blocks)
    project["targets"][0]["tempo"] = 100
    path = tmp_path / "change_tempo.sb3"
    write_sb3(path, project)

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.music_tempo == 120.0
    assert vm.state.stage_variables["score"] == 120.0


def test_music_set_instrument_is_no_op(tmp_path):
    """music_setInstrument does not error and does not block execution."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set_inst", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_inst": {
            "opcode": "music_setInstrument",
            "next": "done",
            "parent": "hat",
            "inputs": {"INSTRUMENT": [1, "inst_menu"]},
            "fields": {},
            "topLevel": False,
        },
        "inst_menu": {
            "opcode": "music_menu_INSTRUMENT",
            "next": None,
            "parent": "set_inst",
            "inputs": {},
            "fields": {"INSTRUMENT": ["1", None]},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "set_inst",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "set_instrument.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["done"] == 1
    assert vm.inspect()["unsupported_scripts"] == []


def test_video_sensing_returns_zero(tmp_path):
    """videoSensing_videoOn evaluates to 0 (no camera) in headless mode."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "video_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "video_expr": {
            "opcode": "videoSensing_videoOn",
            "next": None,
            "parent": "store",
            "inputs": {
                "ATTRIBUTE": [1, "attr_menu"],
                "SUBJECT": [1, "subj_menu"],
            },
            "fields": {},
            "topLevel": False,
        },
        "attr_menu": {
            "opcode": "videoSensing_menu_ATTRIBUTE",
            "next": None,
            "parent": "video_expr",
            "inputs": {},
            "fields": {"ATTRIBUTE": ["motion", None]},
            "topLevel": False,
        },
        "subj_menu": {
            "opcode": "videoSensing_menu_SUBJECT",
            "next": None,
            "parent": "video_expr",
            "inputs": {},
            "fields": {"SUBJECT": ["this sprite", None]},
            "topLevel": False,
        },
    }
    path = tmp_path / "video_sensing.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == 0
    assert vm.inspect()["unsupported_scripts"] == []


def test_text2speech_is_no_op(tmp_path):
    """text2speech_speakAndWait runs without error and completes the script."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "speak", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "speak": {
            "opcode": "text2speech_speakAndWait",
            "next": "done",
            "parent": "hat",
            "inputs": {"WORDS": [1, [10, "Hello"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "speak",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "tts.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["done"] == 1
    assert vm.inspect()["unsupported_scripts"] == []


def test_translate_passthrough(tmp_path):
    """translate_getTranslate returns the original text unchanged in headless mode."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "translate_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "translate_expr": {
            "opcode": "translate_getTranslate",
            "next": None,
            "parent": "store",
            "inputs": {
                "WORDS": [1, [10, "hello world"]],
                "LANGUAGE": [1, "lang_menu"],
            },
            "fields": {},
            "topLevel": False,
        },
        "lang_menu": {
            "opcode": "translate_menu_languages",
            "next": None,
            "parent": "translate_expr",
            "inputs": {},
            "fields": {"languages": ["fr", None]},
            "topLevel": False,
        },
    }
    path = tmp_path / "translate.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == "hello world"
    assert vm.inspect()["unsupported_scripts"] == []


def test_translate_viewer_language(tmp_path):
    """translate_getViewerLanguage returns 'en' in headless mode."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "lang_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "lang_expr": {
            "opcode": "translate_getViewerLanguage",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "viewer_lang.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == "en"
    assert vm.inspect()["unsupported_scripts"] == []


def test_extension_stmts_compile_and_run(tmp_path):
    """Extension stmts (pen, music) are accepted by the JIT compiler."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "pen_down", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "pen_down": {"opcode": "pen_penDown", "next": "pen_up", "parent": "hat", "inputs": {}, "fields": {}, "topLevel": False},
        "pen_up": {"opcode": "pen_penUp", "next": "set_tempo", "parent": "pen_down", "inputs": {}, "fields": {}, "topLevel": False},
        "set_tempo": {
            "opcode": "music_setTempo",
            "next": "done",
            "parent": "pen_up",
            "inputs": {"TEMPO": [1, [4, "200"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "set_tempo",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "ext_compiled.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path), enable_compilation=True, lazy_compile_threshold=1)
    vm.run_for(0.2)

    assert vm.state.stage_variables["done"] == 1
    assert vm.state.music_tempo == 200.0
    assert vm.inspect()["unsupported_scripts"] == []


# ---------------------------------------------------------------------------
# TurboWarp built-in extension tests
# ---------------------------------------------------------------------------

def test_tw_is_paused_returns_false(tmp_path):
    """tw_isPaused returns False in headless mode."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "tw_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "tw_expr": {
            "opcode": "tw_isPaused",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "tw_paused.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == False
    assert vm.inspect()["unsupported_scripts"] == []


def test_tw_is_turbo_mode_returns_false(tmp_path):
    """tw_isTurboModeEnabled returns False (no JIT in this VM)."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "tw_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "tw_expr": {
            "opcode": "tw_isTurboModeEnabled",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "tw_turbo.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == False
    assert vm.inspect()["unsupported_scripts"] == []


def test_tw_log_is_no_op(tmp_path):
    """tw_log/warn/error are no-ops that don't block execution."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "log", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "log": {
            "opcode": "tw_log",
            "next": "warn",
            "parent": "hat",
            "inputs": {"INPUT": [1, [10, "hello"]]},
            "fields": {},
            "topLevel": False,
        },
        "warn": {
            "opcode": "tw_warn",
            "next": "err",
            "parent": "log",
            "inputs": {"INPUT": [1, [10, "warn"]]},
            "fields": {},
            "topLevel": False,
        },
        "err": {
            "opcode": "tw_error",
            "next": "done",
            "parent": "warn",
            "inputs": {"INPUT": [1, [10, "err"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "err",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "tw_log.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.3)

    assert vm.state.stage_variables["done"] == 1
    assert vm.inspect()["unsupported_scripts"] == []


def test_runtime_options_get_fps_returns_30(tmp_path):
    """runtime_options_getFPS returns 30 in headless mode."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "fps_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "fps_expr": {
            "opcode": "runtime_options_getFPS",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "rt_fps.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == 30
    assert vm.inspect()["unsupported_scripts"] == []


def test_runtime_options_stage_dimensions(tmp_path):
    """runtime_options_getStageWidth/Height return 480/360."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store_w", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store_w": {
            "opcode": "data_setvariableto",
            "next": "store_h",
            "parent": "hat",
            "inputs": {"VALUE": [1, "width_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "width_expr": {
            "opcode": "runtime_options_getStageWidth",
            "next": None,
            "parent": "store_w",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        "store_h": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "store_w",
            "inputs": {"VALUE": [1, "height_expr"]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
        "height_expr": {
            "opcode": "runtime_options_getStageHeight",
            "next": None,
            "parent": "store_h",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "rt_dims.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.2)

    assert vm.state.stage_variables["score"] == 480
    assert vm.state.stage_variables["done"] == 360
    assert vm.inspect()["unsupported_scripts"] == []


def test_runtime_options_set_fps_is_no_op(tmp_path):
    """runtime_options_setFPS is a no-op that doesn't block the script."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "set_fps", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "set_fps": {
            "opcode": "runtime_options_setFPS",
            "next": "done",
            "parent": "hat",
            "inputs": {"FPS": [1, [4, "60"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "set_fps",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "rt_set_fps.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["done"] == 1
    assert vm.inspect()["unsupported_scripts"] == []


# ---------------------------------------------------------------------------
# Custom / third-party extension graceful fallback tests
# ---------------------------------------------------------------------------

def test_unknown_ext_stmt_runs_gracefully(tmp_path):
    """An unknown third-party extension command runs as a no-op; script is NOT unsupported."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "custom_cmd", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "custom_cmd": {
            "opcode": "myCustomExt_doSomething",
            "next": "done",
            "parent": "hat",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "custom_cmd",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "custom_ext.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["done"] == 1
    assert vm.inspect()["unsupported_scripts"] == []
    graceful = vm.inspect()["graceful_ext_scripts"]
    assert len(graceful) == 1
    assert "myCustomExt_doSomething" in graceful[0]["opcodes"]


def test_unknown_ext_reporter_returns_empty_string(tmp_path):
    """An unknown third-party extension reporter returns '' and is tracked as graceful."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "store", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "store": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "hat",
            "inputs": {"VALUE": [1, "custom_expr"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "custom_expr": {
            "opcode": "myExt_getValue",
            "next": None,
            "parent": "store",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "custom_reporter.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.state.stage_variables["score"] == ""
    assert vm.inspect()["unsupported_scripts"] == []
    graceful = vm.inspect()["graceful_ext_scripts"]
    assert len(graceful) == 1
    assert "myExt_getValue" in graceful[0]["opcodes"]


def test_known_hardware_ext_remains_unsupported(tmp_path):
    """gdxfor (hardware sensor) blocks remain unsupported — script is blocked."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "hw", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "hw": {
            "opcode": "gdxfor_getAcceleration",
            "next": None,
            "parent": "hat",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "hardware_ext.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    assert vm.inspect()["unsupported_scripts"] != []
    assert vm.inspect()["unsupported_scripts"][0]["opcode"] == "gdxfor_getAcceleration"
    assert vm.inspect()["graceful_ext_scripts"] == []


def test_graceful_ext_opcode_coverage_tracked_separately(tmp_path):
    """Custom extension opcodes appear in graceful_by_opcode, not unsupported_by_opcode."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "custom", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "custom": {
            "opcode": "thirdParty_action",
            "next": None,
            "parent": "hat",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
    }
    path = tmp_path / "graceful_coverage.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path))
    vm.run_for(0.1)

    cov = vm.inspect()["opcode_coverage"]
    assert "thirdParty_action" in cov["graceful_by_opcode"]
    assert "thirdParty_action" not in cov.get("unsupported_by_opcode", {})


def test_tw_ext_compiles_and_runs(tmp_path):
    """TurboWarp built-in blocks are accepted by the JIT compiler."""
    stage_blocks = {
        "hat": {"opcode": "event_whenflagclicked", "next": "is_paused", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
        "is_paused": {
            "opcode": "data_setvariableto",
            "next": "set_fps",
            "parent": "hat",
            "inputs": {"VALUE": [1, "tw_paused"]},
            "fields": {"VARIABLE": ["score", "v1"]},
            "topLevel": False,
        },
        "tw_paused": {
            "opcode": "tw_isPaused",
            "next": None,
            "parent": "is_paused",
            "inputs": {},
            "fields": {},
            "topLevel": False,
        },
        "set_fps": {
            "opcode": "runtime_options_setFPS",
            "next": "done",
            "parent": "is_paused",
            "inputs": {"FPS": [1, [4, "60"]]},
            "fields": {},
            "topLevel": False,
        },
        "done": {
            "opcode": "data_setvariableto",
            "next": None,
            "parent": "set_fps",
            "inputs": {"VALUE": [1, [4, "1"]]},
            "fields": {"VARIABLE": ["done", "v2"]},
            "topLevel": False,
        },
    }
    path = tmp_path / "tw_compiled.sb3"
    write_sb3(path, _base_project(blocks_stage=stage_blocks))

    vm = Sb3Vm(load_sb3(path), enable_compilation=True, lazy_compile_threshold=1)
    vm.run_for(0.3)

    assert vm.state.stage_variables["done"] == 1
    assert vm.state.stage_variables["score"] == False
    assert vm.inspect()["unsupported_scripts"] == []
