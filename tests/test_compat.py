from __future__ import annotations

import json
from pathlib import Path

from sb3vm.cli import build_parser, cmd_compat
from sb3vm.vm.compat import (
    FULLY_SUPPORTED,
    PARSED_ONLY,
    PARTIALLY_SUPPORTED,
    UNSUPPORTED,
    compare_subset,
    default_manifest_path,
    run_compat_suite,
)
from tests.test_helpers import write_sb3


def test_compare_subset_reports_nested_mismatch() -> None:
    mismatches = compare_subset({"stage_variables": {"score": 2}}, {"stage_variables": {"score": 1}}, path="root")
    assert mismatches == ["root.stage_variables.score: expected 2, got 1"]


def test_default_compat_manifest_runs_cleanly() -> None:
    report = run_compat_suite(manifest_path=default_manifest_path())

    assert report["summary"]["label_counts"][FULLY_SUPPORTED] == 2
    assert report["summary"]["label_counts"][PARTIALLY_SUPPORTED] == 1
    assert report["summary"]["label_counts"][PARSED_ONLY] == 1
    assert report["summary"]["label_counts"][UNSUPPORTED] == 1
    assert report["summary"]["regression_count"] == 0

    fixture_ids = {item["fixture_id"]: item for item in report["projects"]}
    assert fixture_ids["demo"]["label"] == FULLY_SUPPORTED
    assert fixture_ids["partial_unsupported"]["label"] == PARTIALLY_SUPPORTED
    assert fixture_ids["parsed_only"]["label"] == PARSED_ONLY
    assert fixture_ids["invalid_archive"]["label"] == UNSUPPORTED
    assert fixture_ids["timing_broadcast_wait"]["checkpoint_results"][0]["mismatches"] == []
    assert report["opcode_matrix"]["data_changevariableby"]["seen_count"] >= 2


def test_compat_cli_outputs_json_and_fails_on_regression(tmp_path, capsys) -> None:
    project_path = tmp_path / "ok.sb3"
    write_sb3(
        project_path,
        {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {"v1": ["score", 0]},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {
                        "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                        "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat", "inputs": {"VALUE": [1, [4, "3"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False}
                    },
                    "comments": {},
                    "costumes": [],
                    "sounds": []
                }
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0"}
        },
    )
    final_path = tmp_path / "golden.json"
    final_path.write_text(json.dumps({"stage_variables": {"score": 9}}), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "fixtures": [
                    {
                        "id": "broken",
                        "path": "ok.sb3",
                        "expected_label": FULLY_SUPPORTED,
                        "runtime": {"seconds": 0.1},
                        "expect": {"final_snapshot": "golden.json"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    parser = build_parser()
    args = parser.parse_args(["compat", "--manifest", str(manifest_path), "--fail-on-regression"])

    assert cmd_compat(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["regression_count"] == 1
    assert payload["projects"][0]["label"] == PARTIALLY_SUPPORTED


def test_compat_includes_extra_projects_dir_as_parsed_only(tmp_path) -> None:
    extra_dir = tmp_path / "extra"
    extra_dir.mkdir()
    write_sb3(
        extra_dir / "extra_case.sb3",
        {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {"v1": ["score", 0]},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {
                        "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                        "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False}
                    },
                    "comments": {},
                    "costumes": [],
                    "sounds": []
                }
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0"}
        },
    )

    report = run_compat_suite(manifest_path=default_manifest_path(), extra_projects_dir=extra_dir)
    fixture = next(item for item in report["projects"] if item["fixture_id"] == "extra:extra_case")

    assert fixture["label"] == PARSED_ONLY
    assert fixture["source"] == "extra_projects_dir"
