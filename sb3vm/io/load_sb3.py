from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sb3vm.log import error, get_logger, info, trace
from sb3vm.model.project import Project
from sb3vm.vm.errors import ProjectValidationError


_LOGGER = get_logger(__name__)


def load_sb3(path: str | Path) -> Project:
    path = Path(path)
    info(_LOGGER, "io.load_sb3", "loading sb3 archive %s", path)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            assets: dict[str, bytes] = {}
            project_json: dict | None = None
            for member in zf.infolist():
                payload = zf.read(member.filename)
                trace(_LOGGER, "io.load_sb3", "read zip entry %s bytes=%d", member.filename, len(payload))
                if member.filename == "project.json":
                    try:
                        project_json = json.loads(payload.decode("utf-8"))
                    except UnicodeDecodeError as exc:
                        error(_LOGGER, "io.load_sb3", "project.json is not valid UTF-8 in %s", path, exc_info=True)
                        raise ProjectValidationError("project.json is not valid UTF-8") from exc
                    except json.JSONDecodeError as exc:
                        error(_LOGGER, "io.load_sb3", "project.json is not valid JSON in %s", path, exc_info=True)
                        raise ProjectValidationError(f"project.json is not valid JSON: {exc.msg}") from exc
                else:
                    assets[member.filename] = payload
    except FileNotFoundError:
        error(_LOGGER, "io.load_sb3", "input archive does not exist: %s", path)
        raise
    except zipfile.BadZipFile as exc:
        error(_LOGGER, "io.load_sb3", "invalid sb3 archive %s", path, exc_info=True)
        raise ProjectValidationError("Input file is not a valid .sb3 zip archive") from exc

    if project_json is None:
        error(_LOGGER, "io.load_sb3", "archive %s is missing project.json", path)
        raise ProjectValidationError("Missing project.json in sb3 archive")
    project = Project.from_json(project_json, assets)
    info(_LOGGER, "io.load_sb3", "loaded project %s targets=%d assets=%d", path, len(project.targets), len(project.assets))
    return project
