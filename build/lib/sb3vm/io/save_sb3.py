from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sb3vm.model.project import Project


def save_sb3(project: Project, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project.to_json(), separators=(",", ":")))
        for name, payload in project.assets.items():
            zf.writestr(name, payload)
