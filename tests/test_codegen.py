from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from sb3vm.cli import build_parser, cmd_py_build, cmd_py_export, cmd_py_inspect, cmd_py_run, cmd_py_scaffold, cmd_run, cmd_text
from sb3vm.codegen import CodegenError, build_project, export_project_source, run_authored_project, save_authored_project
from sb3vm.io.load_sb3 import load_sb3
from sb3vm.parse.pretty import render_project_text
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
    stage_blocks = project.targets[0].blocks
    procdef = next(block for block in stage_blocks.values() if block.get("opcode") == "procedures_definition")
    prototype = stage_blocks[procdef["inputs"]["custom_block"][1]]
    argument_input = prototype["inputs"]["arg:bump:0"][1]
    argument_reporter = stage_blocks[argument_input]

    assert [target.name for target in project.targets] == ["Stage", "Hero"]
    assert "broadcast:1" in project.targets[0].broadcasts.values()
    assert prototype["opcode"] == "procedures_prototype"
    assert prototype["shadow"] is True
    assert argument_reporter["opcode"] == "argument_reporter_string_number"
    assert argument_reporter["fields"]["VALUE"] == ["amount", None]
    vm_project, vm = run_authored_project(source, seconds=1.0)
    assert vm_project.to_json()["meta"]["vm"] == "0.0.0"
    assert vm_project.to_json()["meta"]["sb3vmProjectName"] == "demo"
    assert vm.state.stage_variables["score"] == 7.0
    assert vm.state.stage_lists["items"] == ["done"]
    assert vm.state.targets["Stage"].x == 10.0
    assert vm.state.targets["Stage"].visible is True
    assert vm.state.targets["Hero"].visible is False


def test_build_project_from_package_with_relative_imports_and_stdlib_specs(tmp_path: Path) -> None:
    package_dir = tmp_path / "demo_pkg"
    package_dir.mkdir()
    _write_module(
        package_dir / "shared.py",
        """
from sb3vm.codegen import ScratchProject
from sb3vm.codegen.stdlib import svg_costume

project = ScratchProject("pkg-demo")
stage = project.stage
hero = project.sprite("Hero")
score = stage.variable("score", 0)
hero.add_costume(svg_costume("hero", "hero.svg"))
""",
    )
    _write_module(
        package_dir / "__init__.py",
        """
from sb3vm.codegen import wait
from .shared import hero, project, score, stage

@stage.procedure()
def grow(amount):
    return amount + 1

@stage.when_flag_clicked()
def main():
    score = grow(4)
    wait(0.1)
""",
    )

    project = build_project(package_dir)
    exported = export_project_source(project)
    exported_path = _write_module(tmp_path / "pkg_exported.py", exported)
    rebuilt = build_project(exported_path)
    _, vm = run_authored_project(exported_path, seconds=0.5, dt=0.1)

    assert any(target.name == "Hero" for target in rebuilt.targets)
    assert "from sb3vm.codegen.stdlib import CostumeSpec, SoundSpec" in exported
    assert "CostumeSpec(" in exported
    assert vm.state.stage_variables["score"] == 5.0


def test_project_stdlib_namespaces_support_extensions_json_and_csv(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "stdlib_namespaces.py",
        """
from sb3vm.codegen import ScratchProject, join

project = ScratchProject("stdlib-namespaces")
project.stdlib.extensions.pen()
project.stdlib.extensions.requests_network()

config = project.stdlib.json.loads('{"initial_score": 4, "label": "ok"}')
payload = project.stdlib.json.dumps({"label": config["label"], "ready": True}, sort_keys=True)
csv_line = project.stdlib.csv.row("hero", "needs,quotes", 7)
parsed = project.stdlib.csv.parse_row(csv_line)
csv_second_value = parsed[1]

stage = project.stage
score = stage.variable("score", config["initial_score"])
message = stage.variable("message", "")
csv_second = stage.variable("csv_second", "")

@stage.when_flag_clicked()
def main():
    score = 9
    message = join(payload, join("|", csv_line))
    csv_second = csv_second_value
""",
    )

    project, vm = run_authored_project(source, seconds=0.5, dt=0.1)

    assert project.extensions == ["pen", "requests"]
    assert vm.state.stage_variables["score"] == 9.0
    assert vm.state.stage_variables["message"] == '{"label": "ok", "ready": true}|hero,"needs,quotes",7'
    assert vm.state.stage_variables["csv_second"] == "needs,quotes"


def test_pretty_and_export_use_procedure_display_names_not_internal_ids(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "pretty_names.py",
        """
from sb3vm.codegen import ScratchProject, list_item

project = ScratchProject("pretty-names")
stage = project.stage
cur_dir = stage.list("cur_dir", [180, 0, 90, 45, 180, 270])
next_but = stage.variable("next but", 0)

@stage.procedure(proccode="check next %s", argument_names=("next but",))
def check(button_index):
    if list_item(cur_dir, button_index) == 180:
        next_but = button_index + 5
""",
    )

    project = build_project(source)
    rendered = render_project_text(project)
    exported = export_project_source(project)

    assert "arg:check:0" not in rendered
    assert "arg:check:0" not in exported
    assert "next but" in rendered
    assert "def proc_stage_check_next(next_but):" in exported


def test_when_this_sprite_clicked_authoring_round_trips(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "sprite_click_authoring.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("sprite-click-authoring")
stage = project.stage
hero = project.sprite("Hero")
score = stage.variable("score", 0)

@hero.when_this_sprite_clicked()
def on_click():
    score = 11
""",
    )

    project = build_project(source)
    exported = export_project_source(project)
    top_level_blocks = [
        block
        for target in project.targets
        for block in target.blocks.values()
        if block.get("topLevel")
    ]

    assert any(block.get("opcode") == "event_whenthisspriteclicked" for target in project.targets for block in target.blocks.values())
    assert all(isinstance(block.get("x"), (int, float)) for block in top_level_blocks)
    assert all(isinstance(block.get("y"), (int, float)) for block in top_level_blocks)
    assert ".when_this_sprite_clicked()" in exported


def test_build_project_injects_default_costumes_for_targets_without_assets(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "default_costumes.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("default-costumes")
stage = project.stage
hero = project.sprite("Hero")
score = stage.variable("score", 0)

@stage.when_flag_clicked()
def main():
    score = 1

@hero.when_this_sprite_clicked()
def on_click():
    score = 2
""",
    )
    output = tmp_path / "default_costumes.sb3"

    built = save_authored_project(source, output)
    loaded = load_sb3(output)

    assert built.targets[0].costumes
    assert built.targets[1].costumes
    assert built.targets[0].current_costume == 0
    assert built.targets[1].current_costume == 0
    assert loaded.targets[0].costumes
    assert loaded.targets[1].costumes
    assert loaded.targets[0].costumes[0]["dataFormat"] == "svg"
    assert loaded.targets[1].costumes[0]["dataFormat"] == "svg"
    assert re.fullmatch(r"[a-f0-9]{32}", loaded.targets[0].costumes[0]["assetId"])
    assert re.fullmatch(r"[a-f0-9]{32}", loaded.targets[1].costumes[0]["assetId"])
    assert loaded.targets[0].costumes[0]["md5ext"] in loaded.assets
    assert loaded.targets[1].costumes[0]["md5ext"] in loaded.assets


def test_authoring_monitors_round_trip_in_python(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "monitors.py",
        """
from sb3vm.codegen import MonitorSpec, ScratchProject

project = ScratchProject("monitors")
stage = project.stage
hero = project.sprite("Hero")
score = stage.variable("score", 1)
energy = hero.variable("energy", 5)

stage.monitor_variable(score, x=12, y=18, label="Scoreboard")
project.add_monitor(
    MonitorSpec(
        id="energy-monitor",
        opcode="data_variable",
        params={"VARIABLE": "energy"},
        sprite_name="Hero",
        visible=True,
        x=30,
        y=42,
        label="Energy",
    )
)
""",
    )
    output = tmp_path / "monitors.sb3"

    project = build_project(source)
    exported = export_project_source(project)
    exported_path = _write_module(tmp_path / "monitors_exported.py", exported)
    rebuilt = build_project(exported_path)
    save_authored_project(source, output)
    loaded = load_sb3(output)

    assert len(project.monitors) == 2
    assert project.monitors[0]["params"]["VARIABLE"] == "score"
    assert project.monitors[0]["label"] == "Scoreboard"
    assert project.monitors[1]["spriteName"] == "Hero"
    assert project.monitors[1]["label"] == "Energy"
    assert loaded.monitors == project.monitors
    assert rebuilt.monitors == project.monitors
    assert "MonitorSpec(" in exported
    assert "project.add_monitor(" in exported


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
from sb3vm.codegen.stdlib import svg_costume

project = ScratchProject("extended")
project.extensions.append("music")
project.add_asset("hero.svg", b"<svg />")
stage = project.stage
hero = project.sprite("Hero", visible=False, current_costume=1)
hero.add_costume(svg_costume("hero", "hero.svg"))
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

    hero_costume = project.targets[1].costumes[0]
    assert next(iter(project.assets.values())) == b"<svg />"
    assert re.fullmatch(r"[a-f0-9]{32}", hero_costume["assetId"])
    assert hero_costume["md5ext"] in project.assets
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
from sb3vm.codegen.stdlib import svg_costume

project = ScratchProject("roundtrip")
project.add_asset("sprite.svg", b"<svg />")
stage = project.stage
hero = project.sprite("Hero")
hero.add_costume(svg_costume("hero", "sprite.svg", asset_id="sprite"))
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


def test_returning_procedures_round_trip_without_internal_variables(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "returns.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("returns")
stage = project.stage
value = stage.variable("value", 0)
other = stage.variable("other", 0)

@stage.procedure()
def double(n):
    return n + n

@stage.procedure()
def bounce(n):
    return double(n)

@stage.when_flag_clicked()
def main():
    value = double(5)
    other.set(bounce(7))
""",
    )

    project = build_project(source)
    exported = export_project_source(project)
    exported_path = _write_module(tmp_path / "returns_exported.py", exported)
    rebuilt = build_project(exported_path)
    _, vm = run_authored_project(exported_path, seconds=1.0, dt=0.1)

    assert "__sb3vm_internal__" not in exported
    assert "return (n + n)" in exported
    assert "return proc_stage_double(n)" in exported
    assert "value = proc_stage_double(5)" in exported
    assert "other = proc_stage_bounce(7)" in exported
    assert any(target.is_stage for target in rebuilt.targets)
    assert vm.state.stage_variables["value"] == 10.0
    assert vm.state.stage_variables["other"] == 14.0


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


def test_variable_list_and_string_sugar_round_trips(tmp_path: Path) -> None:
    source = _write_module(
        tmp_path / "sugar.py",
        """
from sb3vm.codegen import ScratchProject

project = ScratchProject("sugar")
stage = project.stage
text = stage.variable("text", "Ada")
num = stage.variable("num", -3.7)
length_value = stage.variable("length_value", 0)
first = stage.variable("first", "")
summary = stage.variable("summary", "")
flag = stage.variable("flag", "")
items = stage.list("items", ["A"])

@stage.when_flag_clicked()
def main():
    text.set(text.join("!"))
    first.set(text.letter(1))
    length_value.set(text.length())
    summary.set(items.text())
    items.push(text.letter(2))
    if items.has("d"):
        items.remove(1)
    flag.set(text.contains("A"))
    num.set(num.rounded())
    num.set(num.math("abs"))
""",
    )

    project = build_project(source)
    exported = export_project_source(project)
    exported_path = _write_module(tmp_path / "sugar_exported.py", exported)
    rebuilt = build_project(exported_path)

    assert "text.join(" in exported
    assert "text.letter(" in exported
    assert "text.length()" in exported
    assert "items.text()" in exported
    assert "items.push(" in exported
    assert "items.has(" in exported
    assert "num.rounded()" in exported
    assert "num.math('abs')" in exported
    assert any(target.is_stage for target in rebuilt.targets)


def test_export_example_project_uses_sugar_constants_and_round_trips(tmp_path: Path) -> None:
    source = export_project_source(load_sb3(Path("test.sb3")))
    exported_path = _write_module(tmp_path / "test_exported.py", source)
    rebuilt = build_project(exported_path)

    assert ".create_clone(MYSELF)" in source
    assert ".touching_object(MOUSE_POINTER)" in source
    assert ".push(" in source
    assert ".at(" in source
    assert ".add_costume(" in source
    assert ".add_sound(" in source
    assert "CostumeSpec(" in source
    assert "SoundSpec(" in source
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
