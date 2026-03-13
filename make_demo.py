import json, zipfile
from pathlib import Path
project = {
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
        "chg": {"opcode": "data_changevariableby", "next": None, "parent": "rep", "inputs": {"VALUE": [1, [4, "2"]]}, "fields": {"VARIABLE": ["score", "v1"]}, "topLevel": False}
      },
      "comments": {},
      "costumes": [],
      "sounds": []
    }
  ],
  "monitors": [],
  "extensions": [],
  "meta": {"semver": "3.0.0"}
}
path = Path('examples/demo.sb3')
path.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('project.json', json.dumps(project))
print(path)
