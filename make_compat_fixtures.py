import json
import zipfile
from pathlib import Path


def write_sb3(path: Path, project: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project))


demo_project = {
    "targets": [
        {
            "isStage": True,
            "name": "Stage",
            "variables": {"v1": ["score", 0]},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "hat": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "set": {"opcode": "data_setvariableto", "next": "rep", "parent": "hat", "inputs": {"VALUE": [1, [4, "0"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                "rep": {"opcode": "control_repeat", "next": None, "parent": "set", "inputs": {"TIMES": [1, [4, "5"]], "SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
                "chg": {"opcode": "data_changevariableby", "next": None, "parent": "rep", "inputs": {"VALUE": [1, [4, "2"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
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

partial_project = {
    "targets": [
        {
            "isStage": True,
            "name": "Stage",
            "variables": {"v1": ["score", 0]},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "hat1": {"opcode": "event_whenflagclicked", "next": "set", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat1", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                "hat2": {"opcode": "event_whenflagclicked", "next": "move", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "move": {"opcode": "gdxfor_getAcceleration", "next": None, "parent": "hat2", "inputs": {}, "fields": {}, "topLevel": False},
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

parsed_only_project = {
    "targets": [
        {
            "isStage": True,
            "name": "Stage",
            "variables": {"v1": ["score", 0]},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "hat": {"opcode": "event_whenflagclicked", "next": "repeat", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "repeat": {"opcode": "control_forever", "next": None, "parent": "hat", "inputs": {"SUBSTACK": [2, "chg"]}, "fields": {}, "topLevel": False},
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

timing_project = {
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
                "hat2": {"opcode": "event_whenbroadcastreceived", "next": "set", "parent": None, "inputs": {}, "fields": {"BROADCAST_OPTION": ["go", "b1"]}, "topLevel": True},
                "set": {"opcode": "data_setvariableto", "next": None, "parent": "hat2", "inputs": {"VALUE": [1, [4, "7"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
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


key_backdrop_dialogue_project = {
    "targets": [
        {
            "isStage": True,
            "name": "Stage",
            "variables": {"v1": ["score", 0], "v2": ["done", 0], "v3": ["keyed", 0]},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "hat": {"opcode": "event_whenflagclicked", "next": "switch_wait", "parent": None, "inputs": {}, "fields": {}, "topLevel": True},
                "switch_wait": {"opcode": "looks_switchbackdroptoandwait", "next": "done", "parent": "hat", "inputs": {"BACKDROP": [1, [10, "night"]]}, "fields": {}, "topLevel": False},
                "done": {"opcode": "data_setvariableto", "next": None, "parent": "switch_wait", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["done", "v2"]}, "topLevel": False},
            },
            "comments": {},
            "costumes": [{"name": "day"}, {"name": "night"}],
            "sounds": [],
        },
        {
            "isStage": False,
            "name": "Sprite1",
            "variables": {},
            "lists": {},
            "broadcasts": {},
            "blocks": {
                "backdrop_hat": {"opcode": "event_whenbackdropswitchesto", "next": "say", "parent": None, "inputs": {}, "fields": {"BACKDROP": ["night", None]}, "topLevel": True},
                "say": {"opcode": "looks_say", "next": "score", "parent": "backdrop_hat", "inputs": {"MESSAGE": [1, [10, "night"]]}, "fields": {}, "topLevel": False},
                "score": {"opcode": "data_setvariableto", "next": None, "parent": "say", "inputs": {"VALUE": [1, [4, "7"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False},
                "key_hat": {"opcode": "event_whenkeypressed", "next": "keyed", "parent": None, "inputs": {}, "fields": {"KEY_OPTION": ["space", None]}, "topLevel": True},
                "keyed": {"opcode": "data_setvariableto", "next": None, "parent": "key_hat", "inputs": {"VALUE": [1, [4, "1"]]}, "fields": {"VARIABLE": ["keyed", "v3"]}, "topLevel": False},
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


write_sb3(Path("compat/projects/demo.sb3"), demo_project)
write_sb3(Path("compat/projects/partial_unsupported.sb3"), partial_project)
write_sb3(Path("compat/projects/parsed_only.sb3"), parsed_only_project)
write_sb3(Path("compat/projects/timing_broadcast_wait.sb3"), timing_project)
write_sb3(Path("compat/projects/key_backdrop_dialogue.sb3"), key_backdrop_dialogue_project)
Path("compat/projects/invalid_archive.sb3").write_text("not a zip archive", encoding="utf-8")

print("compat/projects/demo.sb3")
print("compat/projects/partial_unsupported.sb3")
print("compat/projects/parsed_only.sb3")
print("compat/projects/timing_broadcast_wait.sb3")
print("compat/projects/key_backdrop_dialogue.sb3")
print("compat/projects/invalid_archive.sb3")
