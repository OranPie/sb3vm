from __future__ import annotations

import zipfile

import pytest

from sb3vm.io.load_sb3 import load_sb3
from sb3vm.vm.errors import ProjectValidationError
from sb3vm.vm.runtime import Sb3Vm
from tests.test_helpers import write_sb3


def test_missing_project_json_fails_clearly(tmp_path):
    path = tmp_path / "missing_project.sb3"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("asset.txt", b"demo")

    with pytest.raises(ProjectValidationError, match="Missing project.json in sb3 archive"):
        load_sb3(path)


def test_invalid_project_shape_fails_clearly(tmp_path):
    path = tmp_path / "invalid_project.sb3"
    write_sb3(path, {"targets": {}, "monitors": [], "extensions": [], "meta": {}})

    with pytest.raises(ProjectValidationError, match="Project field 'targets' must be a list"):
        load_sb3(path)


def test_malformed_substack_reference_fails_clearly(tmp_path):
    path = tmp_path / "bad_substack.sb3"
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
                    "blocks": {
                        "hat": {
                            "opcode": "event_whenflagclicked",
                            "next": "repeat",
                            "parent": None,
                            "inputs": {},
                            "fields": {},
                            "topLevel": True,
                        },
                        "repeat": {
                            "opcode": "control_repeat",
                            "next": None,
                            "parent": "hat",
                            "inputs": {"TIMES": [1, [4, "2"]], "SUBSTACK": [2, 7]},
                            "fields": {},
                            "topLevel": False,
                        },
                    },
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

    with pytest.raises(ProjectValidationError, match="Malformed block reference input"):
        Sb3Vm(load_sb3(path))
