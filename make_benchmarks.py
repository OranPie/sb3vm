import json
import zipfile
from pathlib import Path


def write_sb3(path: Path, project: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project))


hot_loop_project = {
    "targets": [
        {
            "isStage": True,
            "name": "Stage",
            "variables": {"v1": ["score", 0], "v2": ["total", 0]},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "hat": {"opcode": "event_whenflagclicked", "next": "score_zero", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "score_zero": {"opcode": "data_setvariableto", "next": "total_zero", "parent": "hat", "inputs": {"VALUE": [1, [4, "0"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                "total_zero": {"opcode": "data_setvariableto", "next": "outer_repeat", "parent": "score_zero", "inputs": {"VALUE": [1, [4, "0"]]}, "fields": {"VARIABLE": ["total", "v2"]}, "topLevel": False},
                "outer_repeat": {"opcode": "control_repeat", "next": None, "parent": "total_zero", "inputs": {"TIMES": [1, [4, "2500"]], "SUBSTACK": [2, "change_score"]}, "fields": {}, "topLevel": False},
                "change_score": {"opcode": "data_changevariableby", "next": "change_total", "parent": "outer_repeat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                "change_total": {"opcode": "data_changevariableby", "next": None, "parent": "change_score", "inputs": {"VALUE": [3, "sum_expr"]}, "fields": {"VARIABLE": ["total", "v2"]}, "topLevel": False},
                "sum_expr": {"opcode": "operator_add", "next": None, "parent": "change_total", "inputs": {"NUM1": [3, "score_var"], "NUM2": [1, [4, "7"]]}, "fields": {}, "topLevel": False},
                "score_var": {"opcode": "data_variable", "next": None, "parent": "sum_expr", "inputs": {}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
            },
            "comments": {},
            "costumes": [{"name": "backdrop1"}],
            "sounds": [],
        }
    ],
    "monitors": [],
    "extensions": [],
    "meta": {"semver": "3.0.0"},
}


broadcast_fanout_project = {
    "targets": [
        {
            "isStage": True,
            "name": "Stage",
            "variables": {"v1": ["done", 0]},
            "lists": {},
            "broadcasts": {"b1": "go"},
            "blocks": {
                "hat": {"opcode": "event_whenflagclicked", "next": "repeat", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "repeat": {"opcode": "control_repeat", "next": "done", "parent": "hat", "inputs": {"TIMES": [1, [4, "400"]], "SUBSTACK": [2, "cast"]}, "fields": {}, "topLevel": False},
                "cast": {"opcode": "event_broadcastandwait", "next": None, "parent": "repeat", "inputs": {"BROADCAST_INPUT": [1, [10, "go"]]}, "fields": {}, "topLevel": False},
                "done": {"opcode": "data_setvariableto", "next": None, "parent": "repeat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["done", "v1"]}, "topLevel": False},
            },
            "comments": {},
            "costumes": [{"name": "backdrop1"}],
            "sounds": [],
        },
        {
            "isStage": False,
            "name": "Sprite1",
            "variables": {"sv1": ["score", 0]},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "hat2": {"opcode": "event_whenbroadcastreceived", "next": "inner_repeat", "parent": None, "inputs": {}, "fields": {"BROADCAST_OPTION": ["go", "b1"]}, "topLevel": True},
                "inner_repeat": {"opcode": "control_repeat", "next": None, "parent": "hat2", "inputs": {"TIMES": [1, [4, "40"]], "SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
                "chg": {"opcode": "data_changevariableby", "next": None, "parent": "inner_repeat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "sv1"]}, "topLevel": False},
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


write_sb3(Path("examples/benchmark_hot_loop.sb3"), hot_loop_project)
write_sb3(Path("examples/benchmark_broadcast_fanout.sb3"), broadcast_fanout_project)

print("examples/benchmark_hot_loop.sb3")
print("examples/benchmark_broadcast_fanout.sb3")
