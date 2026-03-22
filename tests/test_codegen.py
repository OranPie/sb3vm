from __future__ import annotations

import json
from pathlib import Path

import pytest

from sb3vm.cli import build_parser, cmd_py_build, cmd_py_export, cmd_py_inspect, cmd_py_run, cmd_py_scaffold, cmd_run, cmd_text
from sb3vm.codegen import CodegenError, build_project, export_project_source, run_authored_project, save_authored_project
from sb3vm.io.load_sb3 import load_sb3
from sb3vm.parse.extract_scripts import extract_scripts


def _write_module(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_build_project_from_decorated_module(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "authoring_demo.py",
        """
from sb3vm.codegen import ScratchProject, add_to_list, broadcast_wait, goto_xy, hide, wait

project = ScratchProject("demo")
stage = project.stage
hero = project.sprite("Hero")
score = stage.variable("score", 0)
items = stage.list("items", [])

@stage.procedure()
def bump(amount):
    score += amount

@stage.when_flag_clicked()
def main():
    score = 1
    for _ in range(3):
        bump(2)
    add_to_list(items, "done")
    goto_xy(10, -5)
    wait(0.1)
    stop(StopTarget.THIS_SCRIPT)
    broadcast_wait("go")

@hero.when_broadcast_received("go")
def on_go():
    hide()
""",
    )

    project = build_project(source)

    assert [target.name for target in project.targets] == ["Stage", "Hero"]
    assert "broadcast:1" in project.targets[0].broadcasts.values()
    vm_project, vm = run_authored_project(source, seconds=1.0)
    assert vm_project.to_json()["meta"]["vm"] == "demo"
    assert vm.state.stage_variables["score"] == 7.0
    assert vm.state.stage_lists["items"] == ["done"]
    assert vm.state.targets["Stage"].x == 10.0
    assert vm.state.targets["Stage"].visible is True
    assert vm.state.targets["Hero"].visible is False


def test_py_build_run_export_inspect_and_scaffold_cli(tmp_path: Path, capsys) -> None:
    source = _write_module(
        tmp_path / "authoring_cli.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("cli")
stage = project.stage
score = stage.variable("score", 0)

@stage.when_flag_clicked()
def main():
    score = 9
""",
    )
    out = tmp_path / "out.sb3"
    exported = tmp_path / "exported.py"
    parser = build_parser()

    build_args = parser.parse_args(["py-build", str(source), str(out)])
    assert cmd_py_build(build_args) == 0
    assert load_sb3(out).targets[0].variables
    capsys.readouterr()

    export_args = parser.parse_args(["py-export", str(out), str(exported)])
    assert cmd_py_export(export_args) == 0
    assert "ScratchProject" in exported.read_text(encoding="utf-8")
    capsys.readouterr()

    run_args = parser.parse_args(["py-run", str(source), "--seconds", "0.1"])
    assert cmd_py_run(run_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage_variables"]["score"] == 9

    scaffold_path = tmp_path / "scaffold.py"
    scaffold_args = parser.parse_args(["py-scaffold", str(scaffold_path)])
    assert cmd_py_scaffold(scaffold_args) == 0
    assert "ScratchProject" in scaffold_path.read_text(encoding="utf-8")
    capsys.readouterr()

    inspect_args = parser.parse_args(["py-inspect", str(scaffold_path)])
    assert cmd_py_inspect(inspect_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project"]["targets"][0]["name"] == "Stage"
    assert payload["vm_inspect"]["script_count"] >= 1


def test_codegen_rejects_unsupported_local_assignment(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "bad.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("bad")
stage = project.stage

@stage.when_flag_clicked()
def main():
    local = 1
""",
    )

    with pytest.raises(CodegenError, match="declared Scratch variable"):
        build_project(source)


def test_extended_authoring_api_supports_full_parsed_surface(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "extended.py",
        """
from sb3vm.codegen import (
    EDGE,
    GraphicEffect,
    LayerDirection,
    LayerPosition,
    MOUSE_POINTER,
    MYSELF,
    RotationStyle,
    ScratchProject,
    StopTarget,
    ask,
    change_effect_by,
    change_size_by,
    create_clone,
    delete_from_list,
    delete_this_clone,
    glide_to,
    goto_target,
    key_pressed,
    play_note_for_beats,
    point_towards,
    reset_timer,
    say_for_secs,
    switch_backdrop,
    touching_object,
    wait,
)

project = ScratchProject("extended")
project.extensions.append("music")
project.add_asset("hero.svg", b"<svg />")
stage = project.stage
hero = project.sprite("Hero", visible=False, current_costume=1)
hero.costumes.append({"name": "hero", "assetId": "hero", "dataFormat": "svg", "md5ext": "hero.svg", "rotationCenterX": 0, "rotationCenterY": 0})
count = hero.variable("count", 0)
items = hero.list("items", ["a", "b"])

@hero.procedure(warp=True, proccode="bump %s", argument_names=("amount",), argument_defaults=("1",))
def bump(value):
    count += value

@hero.when_flag_clicked()
def start():
    create_clone(MYSELF)
    glide_to(0.5, MOUSE_POINTER)
    goto_target("Hero")
    point_towards(MOUSE_POINTER)
    say_for_secs("hi", 1)
    change_size_by(5)
    change_effect_by(GraphicEffect.GHOST, 10)
    if touching_object(MOUSE_POINTER):
        delete_from_list(items, 1)
    switch_backdrop("scene2")
    set_rotation_style(RotationStyle.LEFT_RIGHT)
    go_front_back(LayerPosition.FRONT)
    go_layers(LayerDirection.FORWARD, 1)
    ask("name?")
    reset_timer()
    play_note_for_beats(60, 0.25)

@hero.when_started_as_clone()
def clone_main():
    bump(2)
    delete_this_clone()

@hero.when_key_pressed("space")
def on_key():
    if key_pressed("space"):
        wait(0.1)

@hero.when_backdrop_switched_to("scene2")
def on_backdrop():
    pass
""",
    )

    project = build_project(source)
    parsed = extract_scripts(project)
    opcodes = {block.get("opcode") for target in project.targets for block in target.blocks.values()}

    assert project.assets["hero.svg"] == b"<svg />"
    assert project.extensions == ["music"]
    assert any(script.trigger.kind == "clone_start" for script in parsed.scripts)
    assert any(script.trigger.kind == "key_pressed" for script in parsed.scripts)
    assert any(script.trigger.kind == "backdrop_switched" for script in parsed.scripts)
    procedure = next(proc for proc in parsed.procedures if proc.target_name == "Hero")
    assert procedure.proccode == "bump %s"
    assert procedure.argument_names == ["amount"]
    assert procedure.argument_defaults == ["1"]
    assert {
        "control_start_as_clone",
        "control_create_clone_of",
        "motion_glideto",
        "motion_goto",
        "motion_pointtowards",
        "looks_sayforsecs",
        "looks_changesizeby",
        "looks_changeeffectby",
        "sensing_touchingobject",
        "event_whenkeypressed",
        "event_whenbackdropswitchesto",
        "sensing_askandwait",
        "sensing_resettimer",
        "music_playNoteForBeats",
    } <= opcodes


def test_export_project_source_round_trips_assets_and_clone_scripts(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "roundtrip_source.py",
        """
from sb3vm.codegen import MYSELF, ScratchProject, StopTarget, create_clone, delete_this_clone, stop, wait

project = ScratchProject("roundtrip")
project.add_asset("sprite.svg", b"<svg />")
stage = project.stage
hero = project.sprite("Hero")
hero.costumes.append({"name": "hero", "assetId": "sprite", "dataFormat": "svg", "md5ext": "sprite.svg", "rotationCenterX": 0, "rotationCenterY": 0})
count = hero.variable("count", 0)

@hero.procedure(proccode="bump %s", argument_names=("amount",), argument_defaults=("1",))
def bump(value):
    count += value

@hero.when_flag_clicked()
def start():
    create_clone(MYSELF)
    wait(0.1)

@hero.when_started_as_clone()
def clone_main():
    bump(2)
    delete_this_clone()
""",
    )
    sb3_path = tmp_path / "roundtrip.sb3"
    exported_path = tmp_path / "roundtrip_exported.py"

    original = save_authored_project(source, sb3_path)
    exported_source = export_project_source(load_sb3(sb3_path))
    exported_path.write_text(exported_source, encoding="utf-8")
    rebuilt = build_project(exported_path)

    assert "when_started_as_clone" in exported_source
    assert "create_clone" in exported_source
    assert "project.add_asset" in exported_source
    assert "proccode=" in exported_source
    assert rebuilt.assets == original.assets
    assert rebuilt.extensions == original.extensions
    rebuilt_parsed = extract_scripts(rebuilt)
    assert any(script.trigger.kind == "clone_start" for script in rebuilt_parsed.scripts)
    assert any(proc.proccode == "bump %s" for proc in rebuilt_parsed.procedures)


def test_export_project_source_handles_stage_variable_used_from_sprite(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "cross_scope.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("cross-scope")
stage = project.stage
buttons = project.sprite("Buttons")
highest = stage.variable("Highest", "")

@buttons.procedure(proccode="Check Highest")
def check_highest():
    highest = "Score"
""",
    )

    project = build_project(source)
    exported = export_project_source(project)
    exported_path = _write_module(tmp_path / "cross_scope_exported.py", exported)
    rebuilt = build_project(exported_path)

    assert "highest = stage.variable(\"Highest\", '')" in exported
    rebuilt_stage = next(target for target in rebuilt.targets if target.is_stage)
    assert any(name == "Highest" for _, (name, _) in rebuilt_stage.variables.items())


def test_export_example_project_uses_sugar_constants_and_round_trips(tmp_path: Path) -> None:
    source = export_project_source(load_sb3(Path("test.sb3")))
    exported_path = _write_module(tmp_path / "test_exported.py", source)
    rebuilt = build_project(exported_path)

    assert ".create_clone(MYSELF)" in source
    assert ".touching_object(MOUSE_POINTER)" in source
    assert ".append(" in source
    assert ".item(" in source
    assert ".add_costume(" in source
    assert ".add_sound(" in source
    assert ".costumes.extend(" not in source
    assert ".sounds.extend(" not in source
    assert "GraphicEffect." in source
    assert "RotationStyle." in source
    assert "None == None" not in source
    assert "None < None" not in source
    assert "None > None" not in source
    assert any(target.name == "Buttons" for target in rebuilt.targets)


def test_text_cli_and_run_status_output(tmp_path: Path, capsys) -> None:
    source = _write_module(
        tmp_path / "status_demo.py",
        """
from sb3vm.codegen import ScratchProject, wait

project = ScratchProject("status-demo")
stage = project.stage
score = stage.variable("score", 0)

@stage.when_flag_clicked()
def main():
    score = 1
    wait(0.2)
    score = 2
""",
    )
    out = tmp_path / "status_demo.sb3"
    save_authored_project(source, out)
    parser = build_parser()

    text_args = parser.parse_args(["text", str(out)])
    assert cmd_text(text_args) == 0
    text_output = capsys.readouterr().out
    assert "Project: status-demo" in text_output
    assert "when green flag clicked" in text_output
    assert "wait(0.2)" in text_output

    run_args = parser.parse_args(["run", str(out), "--seconds", "0.3", "--dt", "0.1", "--status"])
    assert cmd_run(run_args) == 0
    run_output = capsys.readouterr().out
    assert "threads=" in run_output
    assert "stmt=wait(0.2)" in run_output
    assert '"thread_status"' in run_output
