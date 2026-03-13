from __future__ import annotations

import json
from pathlib import Path

import pytest

from sb3vm.cli import build_parser, cmd_py_build, cmd_py_inspect, cmd_py_run, cmd_py_scaffold
from sb3vm.codegen import CodegenError, build_project, run_authored_project
from sb3vm.io.load_sb3 import load_sb3


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


def test_py_build_and_run_cli(tmp_path: Path, capsys) -> None:
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
    parser = build_parser()

    build_args = parser.parse_args(["py-build", str(source), str(out)])
    assert cmd_py_build(build_args) == 0
    assert load_sb3(out).targets[0].variables
    capsys.readouterr()

    run_args = parser.parse_args(["py-run", str(source), "--seconds", "0.1"])
    assert cmd_py_run(run_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage_variables"]["score"] == 9


def test_py_inspect_and_scaffold_cli(tmp_path: Path, capsys) -> None:
    parser = build_parser()
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
