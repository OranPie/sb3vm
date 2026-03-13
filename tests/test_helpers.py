from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def write_sb3(path: Path, project_json: dict, *, assets: dict[str, bytes] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project_json))
        for name, payload in (assets or {}).items():
            zf.writestr(name, payload)


def fixture_project(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
