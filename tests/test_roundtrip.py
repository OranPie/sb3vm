from __future__ import annotations

import json
import zipfile

from sb3vm.io.load_sb3 import load_sb3
from sb3vm.io.save_sb3 import save_sb3
from tests.test_helpers import fixture_project, write_sb3


def test_roundtrip_preserves_structure(tmp_path):
    src = tmp_path / "in.sb3"
    dst = tmp_path / "out.sb3"
    project_json = {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {"v1": ["score", 0]},
                "lists": {},
                "broadcasts": {"b1": "start"},
                "blocks": {},
                "comments": {},
                "costumes": [{"assetId": "abc", "md5ext": "abc.svg", "name": "backdrop1"}],
                "sounds": [],
            }
        ],
        "monitors": [],
        "extensions": [],
        "meta": {"semver": "3.0.0"},
    }
    write_sb3(src, project_json)
    project = load_sb3(src)
    save_sb3(project, dst)
    with zipfile.ZipFile(dst, "r") as zf:
        payload = json.loads(zf.read("project.json"))
    assert payload["targets"][0]["variables"]["v1"] == ["score", 0]
    assert payload["meta"]["semver"] == "3.0.0"


def test_roundtrip_preserves_raw_fields_and_assets(tmp_path):
    src = tmp_path / "rich_in.sb3"
    dst = tmp_path / "rich_out.sb3"
    project_json = fixture_project("roundtrip_rich_project")
    assets = {
        "abc.svg": b"<svg>stage</svg>",
        "sprite.svg": b"<svg>sprite</svg>",
        "snd.wav": b"RIFFdemo",
    }
    write_sb3(src, project_json, assets=assets)

    project = load_sb3(src)
    save_sb3(project, dst)

    with zipfile.ZipFile(dst, "r") as zf:
        payload = json.loads(zf.read("project.json"))
        archive_names = sorted(zf.namelist())
        assert zf.read("abc.svg") == assets["abc.svg"]
        assert zf.read("snd.wav") == assets["snd.wav"]

    assert archive_names == ["abc.svg", "project.json", "snd.wav", "sprite.svg"]
    assert payload["extraTopLevel"] == {"preserve": True}
    assert payload["targets"][0]["customField"] == {"nested": [1, 2, 3]}
    assert payload["targets"][0]["comments"]["c1"]["text"] == "keep me"
    assert payload["monitors"][0]["opcode"] == "data_variable"
    assert payload["extensions"] == ["pen"]
