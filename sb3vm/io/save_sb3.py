from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sb3vm.log import debug, get_logger, info, instrument_module
from sb3vm.model.project import Project


_LOGGER = get_logger(__name__)


def save_sb3(project: Project, path: str | Path) -> None:
    path = Path(path)
    info(_LOGGER, "io.save_sb3", "saving project %s to %s", project.meta.get("vm", project.meta.get("semver", "unknown")), path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project.to_json(), separators=(",", ":")))
        for name, payload in project.assets.items():
            debug(_LOGGER, "io.save_sb3", "writing asset %s bytes=%d", name, len(payload))
            zf.writestr(name, payload)
    info(_LOGGER, "io.save_sb3", "saved archive %s assets=%d", path, len(project.assets))


instrument_module(globals(), _LOGGER)
