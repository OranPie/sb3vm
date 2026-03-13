from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sb3vm.model.project import Project
from sb3vm.vm.errors import ProjectValidationError


def load_sb3(path: str | Path) -> Project:
    path = Path(path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            assets: dict[str, bytes] = {}
            project_json: dict | None = None
            for info in zf.infolist():
                payload = zf.read(info.filename)
                if info.filename == "project.json":
                    try:
                        project_json = json.loads(payload.decode("utf-8"))
                    except UnicodeDecodeError as exc:
                        raise ProjectValidationError("project.json is not valid UTF-8") from exc
                    except json.JSONDecodeError as exc:
                        raise ProjectValidationError(f"project.json is not valid JSON: {exc.msg}") from exc
                else:
                    assets[info.filename] = payload
    except FileNotFoundError:
        raise
    except zipfile.BadZipFile as exc:
        raise ProjectValidationError("Input file is not a valid .sb3 zip archive") from exc

    if project_json is None:
        raise ProjectValidationError("Missing project.json in sb3 archive")
    return Project.from_json(project_json, assets)
